"""
k6_parser.py
Parses k6 JSON output (from `k6 run --out json=output.json`) into the same metrics dict shape
as results_parser.parse_results().

k6 emits one JSON object per line. Each Point carries a metric name and tags:
    {"type":"Point","metric":"http_req_duration","data":{
        "time":"2024-01-01T00:00:00Z","value":123.4,
        "tags":{"name":"/orders","status":"200","method":"GET","expected_response":"true"}}}
We aggregate http_req_duration points keyed by tag.name (falling back to tag.url) and use the
status tag + expected_response to determine success.

Public function: parse_results(json_path: str) -> dict
"""

import json
import pandas as pd
from pathlib import Path


def parse_results(json_path: str) -> dict:
    df = _load_k6_json(json_path)
    return {
        "summary":         _compute_summary(df),
        "endpoints":       _compute_per_endpoint(df),
        "errors":          _compute_errors(df),
        "errors_by_label": _compute_errors_by_label(df),
        "timeline":        _compute_timeline(df),
    }


def _load_k6_json(path: str) -> pd.DataFrame:
    rows = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("type") != "Point":
                continue
            if obj.get("metric") != "http_req_duration":
                continue

            data = obj.get("data", {})
            tags = data.get("tags", {}) or {}
            label = tags.get("name") or tags.get("url") or "(unknown)"
            status = str(tags.get("status", ""))
            expected = str(tags.get("expected_response", "true")).lower() == "true"
            success = expected and status.startswith("2")

            rows.append({
                "label":           label,
                "timestamp":       data.get("time"),
                "elapsed":         float(data.get("value", 0)),
                "success":         success,
                "responsecode":    status or "0",
                "responsemessage": tags.get("error", ""),
            })

    if not rows:
        raise ValueError(
            "k6 JSON contained no http_req_duration Points. "
            "Did you run `k6 run --out json=output.json`?"
        )

    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["timestamp"])
    return df


def _compute_summary(df: pd.DataFrame) -> dict:
    duration_s = (df["timestamp"].max() - df["timestamp"].min()).total_seconds()
    total = len(df)
    errors = (~df["success"]).sum()

    return {
        "total_requests":     int(total),
        "duration_seconds":   round(duration_s, 1),
        "throughput_rps":     round(total / duration_s, 2) if duration_s > 0 else 0,
        "error_count":        int(errors),
        "error_rate_pct":     round((errors / total) * 100, 2) if total > 0 else 0,
        "avg_ms":             round(df["elapsed"].mean(), 1),
        "min_ms":             int(df["elapsed"].min()),
        "max_ms":             int(df["elapsed"].max()),
        "p50_ms":             int(df["elapsed"].quantile(0.50)),
        "p90_ms":             int(df["elapsed"].quantile(0.90)),
        "p95_ms":             int(df["elapsed"].quantile(0.95)),
        "p99_ms":             int(df["elapsed"].quantile(0.99)),
        "std_ms":             round(df["elapsed"].std(), 1),
        "max_users":          0,  # k6 JSON Points don't carry VU concurrency per request
        "avg_bandwidth_kbps": 0,
        "test_start":         df["timestamp"].min().strftime("%b, %-d %Y %-I:%M:%S %p"),
        "test_end":           df["timestamp"].max().strftime("%b, %-d %Y %-I:%M:%S %p"),
    }


def _compute_per_endpoint(df: pd.DataFrame) -> dict:
    result = {}
    for label, group in df.groupby("label"):
        total = len(group)
        errors = (~group["success"]).sum()
        result[label] = {
            "total_requests": int(total),
            "error_count":    int(errors),
            "error_rate_pct": round((errors / total) * 100, 2) if total > 0 else 0,
            "avg_ms":         round(group["elapsed"].mean(), 1),
            "min_ms":         int(group["elapsed"].min()),
            "max_ms":         int(group["elapsed"].max()),
            "p50_ms":         int(group["elapsed"].quantile(0.50)),
            "p90_ms":         int(group["elapsed"].quantile(0.90)),
            "p95_ms":         int(group["elapsed"].quantile(0.95)),
            "p99_ms":         int(group["elapsed"].quantile(0.99)),
        }
    return result


def _compute_errors(df: pd.DataFrame) -> dict:
    error_df = df[~df["success"]]
    if error_df.empty:
        return {}

    breakdown = {}
    for code, group in error_df.groupby("responsecode"):
        breakdown[str(code)] = {
            "count":         int(len(group)),
            "pct_of_errors": round(len(group) / len(error_df) * 100, 1),
            "endpoints":     group["label"].value_counts().to_dict(),
        }
    return breakdown


def _compute_errors_by_label(df: pd.DataFrame) -> dict:
    error_df = df[~df["success"]]
    if error_df.empty:
        return {}

    result = {}
    for label, lgroup in error_df.groupby("label"):
        codes = []
        for (code, msg), cgroup in lgroup.groupby(["responsecode", "responsemessage"]):
            codes.append({
                "code":        str(code),
                "description": str(msg) if msg else "—",
                "count":       int(len(cgroup)),
            })
        result[label] = sorted(codes, key=lambda x: -x["count"])
    return result


def _compute_timeline(df: pd.DataFrame) -> list:
    df = df.copy()
    df["bucket"] = df["timestamp"].dt.floor("10s")

    timeline = []
    for bucket, group in df.groupby("bucket"):
        timeline.append({
            "time":         bucket.isoformat(),
            "throughput":   round(len(group) / 10.0, 2),
            "avg_ms":       round(group["elapsed"].mean(), 1),
            "p95_ms":       int(group["elapsed"].quantile(0.95)),
            "error_rate":   round((~group["success"]).mean() * 100, 2),
            "active_users": 0,
        })

    return sorted(timeline, key=lambda x: x["time"])
