"""
loadrunner_parser.py
Parses a LoadRunner Analysis CSV export into the same metrics dict shape as
results_parser.parse_results().

LoadRunner Analysis can export several CSV formats. We support the two most common:

1. **Raw Data export** (Analysis -> Tools -> Raw Data -> Export to CSV).
   Columns typically include: "Transaction Name", "Start Time", "End Time",
   "Response Time", "Status" (Pass/Fail), "Vuser ID".

2. **Transaction Summary export** (Analysis -> Report -> Summary Report -> Save As CSV).
   Per-transaction aggregated rows with: "Transaction Name", "Count", "Average (sec)",
   "Maximum (sec)", "Minimum (sec)", "90% (sec)", "Fail".
   Used only as fallback when raw data is not available; produces summary-only metrics.

The Raw Data path is preferred because it allows the full PerfAI pipeline (timeline,
percentiles, errors-by-label) to work identically to JMeter.

Public function: parse_results(csv_path: str) -> dict
"""

import pandas as pd
from pathlib import Path


def parse_results(csv_path: str) -> dict:
    df_raw = _try_load_raw(csv_path)
    if df_raw is not None:
        return _metrics_from_raw(df_raw)

    df_sum = _try_load_summary(csv_path)
    if df_sum is not None:
        return _metrics_from_summary(df_sum)

    raise ValueError(
        "LoadRunner CSV does not match the expected Raw Data or Transaction Summary format. "
        "Export from LoadRunner Analysis via: Tools -> Raw Data -> Export to CSV "
        "(preferred), or Report -> Summary -> Save As CSV."
    )


# -- raw-data path -------------------------------------------------------------

def _try_load_raw(path: str):
    """Return a normalised DataFrame if the file looks like a Raw Data export, else None."""
    try:
        df = pd.read_csv(path)
    except Exception:
        return None

    cols_lower = {c.strip().lower(): c for c in df.columns}

    name_col = _first_present(cols_lower, ["transaction name", "name", "label"])
    elapsed_col = _first_present(cols_lower, ["response time", "duration", "elapsed", "transaction response time"])
    start_col = _first_present(cols_lower, ["start time", "timestamp", "time"])
    status_col = _first_present(cols_lower, ["status", "result", "pass/fail"])

    if not (name_col and elapsed_col and start_col):
        return None

    out = pd.DataFrame({
        "label":     df[name_col].astype(str),
        "elapsed_s": pd.to_numeric(df[elapsed_col], errors="coerce"),
        "timestamp": pd.to_datetime(df[start_col], errors="coerce"),
    })

    if status_col:
        s = df[status_col].astype(str).str.lower()
        out["success"] = s.isin(["pass", "passed", "ok", "success", "1", "true"])
    else:
        out["success"] = True

    out = out.dropna(subset=["elapsed_s", "timestamp"])
    if out.empty:
        return None

    # LoadRunner elapsed is usually seconds; convert to milliseconds for parity with JTL.
    out["elapsed"] = (out["elapsed_s"] * 1000).round().astype(int)
    out["responsecode"] = out["success"].map({True: "OK", False: "FAILED"})
    out["responsemessage"] = ""
    return out


def _metrics_from_raw(df: pd.DataFrame) -> dict:
    return {
        "summary":         _compute_summary(df),
        "endpoints":       _compute_per_endpoint(df),
        "errors":          _compute_errors(df),
        "errors_by_label": _compute_errors_by_label(df),
        "timeline":        _compute_timeline(df),
    }


# -- summary-only fallback path ------------------------------------------------

def _try_load_summary(path: str):
    try:
        df = pd.read_csv(path)
    except Exception:
        return None

    cols_lower = {c.strip().lower(): c for c in df.columns}

    name_col = _first_present(cols_lower, ["transaction name", "name"])
    count_col = _first_present(cols_lower, ["count", "pass", "passed"])
    avg_col = _first_present(cols_lower, ["average (sec)", "average", "avg (sec)", "avg"])
    p90_col = _first_present(cols_lower, ["90% (sec)", "p90 (sec)", "p90", "90%"])
    max_col = _first_present(cols_lower, ["maximum (sec)", "max (sec)", "max"])
    min_col = _first_present(cols_lower, ["minimum (sec)", "min (sec)", "min"])
    fail_col = _first_present(cols_lower, ["fail", "failed", "errors"])

    if not (name_col and count_col and avg_col):
        return None

    out = pd.DataFrame({
        "label":  df[name_col].astype(str),
        "count":  pd.to_numeric(df[count_col], errors="coerce").fillna(0).astype(int),
        "avg_s":  pd.to_numeric(df[avg_col], errors="coerce"),
        "p90_s":  pd.to_numeric(df[p90_col], errors="coerce") if p90_col else 0,
        "max_s":  pd.to_numeric(df[max_col], errors="coerce") if max_col else 0,
        "min_s":  pd.to_numeric(df[min_col], errors="coerce") if min_col else 0,
        "fail":   pd.to_numeric(df[fail_col], errors="coerce").fillna(0).astype(int) if fail_col else 0,
    })
    out = out.dropna(subset=["avg_s"])
    return out if not out.empty else None


def _metrics_from_summary(df: pd.DataFrame) -> dict:
    """Build a metrics dict from aggregated summary data only — no timeline."""
    total = int(df["count"].sum())
    errors = int(df["fail"].sum()) if "fail" in df.columns else 0
    avg_ms = round((df["avg_s"] * df["count"]).sum() / total * 1000, 1) if total > 0 else 0
    max_ms = int(df["max_s"].max() * 1000) if "max_s" in df.columns else 0
    min_ms = int(df["min_s"].min() * 1000) if "min_s" in df.columns else 0
    p90_ms = int(df["p90_s"].max() * 1000) if "p90_s" in df.columns else 0

    summary = {
        "total_requests":     total,
        "duration_seconds":   0,  # summary export has no duration
        "throughput_rps":     0,
        "error_count":        errors,
        "error_rate_pct":     round((errors / total) * 100, 2) if total > 0 else 0,
        "avg_ms":             avg_ms,
        "min_ms":             min_ms,
        "max_ms":             max_ms,
        "p50_ms":             avg_ms,
        "p90_ms":             p90_ms,
        "p95_ms":             p90_ms,
        "p99_ms":             max_ms,
        "std_ms":             0,
        "max_users":          0,
        "avg_bandwidth_kbps": 0,
        "test_start":         "—",
        "test_end":           "—",
    }

    endpoints = {}
    for _, row in df.iterrows():
        count = int(row["count"])
        fail = int(row.get("fail", 0))
        endpoints[str(row["label"])] = {
            "total_requests": count,
            "error_count":    fail,
            "error_rate_pct": round((fail / count) * 100, 2) if count > 0 else 0,
            "avg_ms":         round(row["avg_s"] * 1000, 1),
            "min_ms":         int(row.get("min_s", 0) * 1000),
            "max_ms":         int(row.get("max_s", 0) * 1000),
            "p50_ms":         round(row["avg_s"] * 1000, 1),
            "p90_ms":         int(row.get("p90_s", 0) * 1000),
            "p95_ms":         int(row.get("p90_s", 0) * 1000),
            "p99_ms":         int(row.get("max_s", 0) * 1000),
        }

    return {
        "summary":         summary,
        "endpoints":       endpoints,
        "errors":          {},
        "errors_by_label": {},
        "timeline":        [],
    }


# -- shared raw-data helpers (mirror results_parser.py shape) ------------------

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
        "max_users":          0,
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
        for code, cgroup in lgroup.groupby("responsecode"):
            codes.append({
                "code":        str(code),
                "description": "—",
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


def _first_present(cols_lower: dict, candidates: list):
    for c in candidates:
        if c in cols_lower:
            return cols_lower[c]
    return None
