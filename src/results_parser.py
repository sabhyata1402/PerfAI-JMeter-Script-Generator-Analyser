"""
results_parser.py
Parses a JMeter .jtl results file (CSV format) into structured performance metrics.
Public function: parse_results(jtl_path: str) -> dict
"""

import pandas as pd
import numpy as np
from pathlib import Path


def parse_results(jtl_path: str) -> dict:
    """
    Parse a JMeter .jtl file and return comprehensive performance metrics.

    Returns a dict:
    {
        "summary": { overall stats },
        "endpoints": { label: { per-endpoint stats } },
        "errors":    { error breakdown },
        "timeline":  [ { time, throughput, avg_rt } ],   # for charts
    }
    """
    df = _load_jtl(jtl_path)
    return {
        "summary":        _compute_summary(df),
        "endpoints":      _compute_per_endpoint(df),
        "errors":         _compute_errors(df),
        "errors_by_label":_compute_errors_by_label(df),
        "timeline":       _compute_timeline(df),
    }


# ── internal helpers ──────────────────────────────────────────────────────────

def _load_jtl(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)

    # Normalise column names (JMeter versions differ slightly)
    df.columns = [c.strip().lower() for c in df.columns]

    # Ensure required columns exist
    required = {"timestamp", "elapsed", "label", "responsecode", "success"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"JTL file missing columns: {missing}")

    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df["elapsed"] = pd.to_numeric(df["elapsed"], errors="coerce")
    df["success"] = df["success"].astype(str).str.lower().map({"true": True, "false": False})
    df["responsecode"] = df["responsecode"].astype(str)

    return df.dropna(subset=["elapsed"])


def _compute_summary(df: pd.DataFrame) -> dict:
    duration_s = (df["timestamp"].max() - df["timestamp"].min()).total_seconds()
    total = len(df)
    errors = (~df["success"]).sum()

    max_users = 0
    if "allthreads" in df.columns:
        max_users = int(pd.to_numeric(df["allthreads"], errors="coerce").max() or 0)

    avg_bandwidth_kbps = 0
    if "bytes" in df.columns:
        total_bytes = pd.to_numeric(df["bytes"], errors="coerce").sum()
        avg_bandwidth_kbps = round(total_bytes / duration_s / 1024, 2) if duration_s > 0 else 0

    return {
        "total_requests":      int(total),
        "duration_seconds":    round(duration_s, 1),
        "throughput_rps":      round(total / duration_s, 2) if duration_s > 0 else 0,
        "error_count":         int(errors),
        "error_rate_pct":      round((errors / total) * 100, 2) if total > 0 else 0,
        "avg_ms":              round(df["elapsed"].mean(), 1),
        "min_ms":              int(df["elapsed"].min()),
        "max_ms":              int(df["elapsed"].max()),
        "p50_ms":              int(df["elapsed"].quantile(0.50)),
        "p90_ms":              int(df["elapsed"].quantile(0.90)),
        "p95_ms":              int(df["elapsed"].quantile(0.95)),
        "p99_ms":              int(df["elapsed"].quantile(0.99)),
        "std_ms":              round(df["elapsed"].std(), 1),
        "max_users":           max_users,
        "avg_bandwidth_kbps":  avg_bandwidth_kbps,
        "test_start":          df["timestamp"].min().strftime("%b, %-d %Y %-I:%M:%S %p"),
        "test_end":            df["timestamp"].max().strftime("%b, %-d %Y %-I:%M:%S %p"),
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
        breakdown[code] = {
            "count": int(len(group)),
            "pct_of_errors": round(len(group) / len(error_df) * 100, 1),
            "endpoints": group["label"].value_counts().to_dict(),
        }
    return breakdown


def _compute_errors_by_label(df: pd.DataFrame) -> dict:
    """Return errors grouped by endpoint label, each with a list of {code, description, count}."""
    error_df = df[~df["success"]]
    if error_df.empty:
        return {}

    result = {}
    group_cols = ["label", "responsecode"]
    if "responsemessage" in error_df.columns:
        group_cols.append("responsemessage")

    for label, lgroup in error_df.groupby("label"):
        codes = []
        if "responsemessage" in lgroup.columns:
            for (code, msg), cgroup in lgroup.groupby(["responsecode", "responsemessage"]):
                codes.append({"code": str(code), "description": str(msg), "count": int(len(cgroup))})
        else:
            for code, cgroup in lgroup.groupby("responsecode"):
                codes.append({"code": str(code), "description": "—", "count": int(len(cgroup))})
        result[label] = sorted(codes, key=lambda x: -x["count"])
    return result


def _compute_timeline(df: pd.DataFrame) -> list[dict]:
    """Bucket requests into 10-second windows for throughput/latency timeline charts."""
    df = df.copy()
    df["bucket"] = df["timestamp"].dt.floor("10s")

    timeline = []
    for bucket, group in df.groupby("bucket"):
        duration = 10  # seconds per bucket
        timeline.append({
            "time":         bucket.isoformat(),
            "throughput":   round(len(group) / duration, 2),
            "avg_ms":       round(group["elapsed"].mean(), 1),
            "p95_ms":       int(group["elapsed"].quantile(0.95)),
            "error_rate":   round((~group["success"]).mean() * 100, 2),
            "active_users": int(group["allthreads"].max()) if "allthreads" in group.columns else 0,
        })

    return sorted(timeline, key=lambda x: x["time"])


def metrics_to_summary_text(metrics: dict) -> str:
    """
    Convert parsed metrics to a structured text block for the Claude analysis prompt.
    Keeps it concise — Claude doesn't need the raw timeline.
    """
    s = metrics["summary"]
    lines = [
        "=== OVERALL SUMMARY ===",
        f"Total requests: {s['total_requests']}",
        f"Duration: {s['duration_seconds']}s",
        f"Throughput: {s['throughput_rps']} req/s",
        f"Error rate: {s['error_rate_pct']}%",
        f"Avg: {s['avg_ms']}ms | p50: {s['p50_ms']}ms | p90: {s['p90_ms']}ms | p95: {s['p95_ms']}ms | p99: {s['p99_ms']}ms",
        "",
        "=== PER ENDPOINT ===",
    ]

    for label, ep in metrics["endpoints"].items():
        lines.append(
            f"{label}: avg={ep['avg_ms']}ms p95={ep['p95_ms']}ms p99={ep['p99_ms']}ms "
            f"errors={ep['error_rate_pct']}% total={ep['total_requests']}"
        )

    if metrics["errors"]:
        lines.append("")
        lines.append("=== ERROR BREAKDOWN ===")
        for code, info in metrics["errors"].items():
            lines.append(f"HTTP {code}: {info['count']} occurrences ({info['pct_of_errors']}% of errors)")

    return "\n".join(lines)
