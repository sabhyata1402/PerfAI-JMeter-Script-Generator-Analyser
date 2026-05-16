"""
gatling_parser.py
Parses a Gatling simulation.log file into the same metrics dict shape as results_parser.parse_results().

Gatling 3.x simulation.log is a tab-separated file with these record types:
    RUN          run-id          simulation-class  simulation-id  description  start-ts  end-ts  version
    REQUEST      scenario        userId            request-name   start-ts    end-ts    status (OK|KO)  message
    USER         scenario        START|END         userId         timestamp
    GROUP        ...
We only care about REQUEST records for metrics.

Public function: parse_results(log_path: str) -> dict
"""

import pandas as pd
from pathlib import Path


def parse_results(log_path: str) -> dict:
    df = _load_gatling_log(log_path)
    return {
        "summary":         _compute_summary(df),
        "endpoints":       _compute_per_endpoint(df),
        "errors":          _compute_errors(df),
        "errors_by_label": _compute_errors_by_label(df),
        "timeline":        _compute_timeline(df),
    }


def _load_gatling_log(path: str) -> pd.DataFrame:
    rows = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if not parts or parts[0] != "REQUEST":
                continue
            # Gatling 3.x REQUEST line layout:
            # REQUEST  scenario  userId  request-name  start-ts  end-ts  status  message
            # Older variants may include groups between scenario and request-name; we read
            # by indexing from the end to stay tolerant.
            if len(parts) < 7:
                continue
            try:
                status = parts[-2]
                end_ts = int(parts[-3])
                start_ts = int(parts[-4])
            except (ValueError, IndexError):
                continue
            request_name = parts[-5] if len(parts) >= 5 else "(unknown)"
            message = parts[-1] if status == "KO" else ""
            rows.append({
                "label":        request_name,
                "timestamp_ms": start_ts,
                "elapsed":      max(0, end_ts - start_ts),
                "success":      status == "OK",
                "responsecode": "OK" if status == "OK" else (message[:32] or "KO"),
                "responsemessage": message,
            })

    if not rows:
        raise ValueError("Gatling simulation.log contained no REQUEST records.")

    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp_ms"], unit="ms")
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
        "max_users":          0,  # Gatling sim log does not carry concurrent-user counts per request
        "avg_bandwidth_kbps": 0,  # Gatling does not record bytes
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
