"""
influxdb_writer.py
Exports PerfAI metrics to an InfluxDB v2 bucket for live Grafana dashboards.
Public function:
    write_metrics(metrics, run_label, url, token, org, bucket) -> None
"""

from datetime import datetime, timezone


def write_metrics(
    metrics: dict,
    run_label: str = "perfai_run",
    url: str = "http://localhost:8086",
    token: str = "",
    org: str = "perfai",
    bucket: str = "perfai",
) -> None:
    """
    Write per-endpoint performance metrics to InfluxDB v2.

    Args:
        metrics:    dict keyed by endpoint label, values are metric dicts
                    (avg_ms, p50_ms, p90_ms, p95_ms, p99_ms, error_rate, throughput_rps, samples)
        run_label:  tag value to distinguish this test run (e.g. "release-1.2.3")
        url:        InfluxDB base URL  (e.g. "http://localhost:8086")
        token:      InfluxDB v2 API token
        org:        InfluxDB organisation name
        bucket:     InfluxDB bucket name
    """
    try:
        from influxdb_client import InfluxDBClient, WriteOptions
        from influxdb_client.client.write_api import SYNCHRONOUS
    except ImportError:
        raise ImportError(
            "influxdb-client is required for InfluxDB export. "
            "Install it with: pip install influxdb-client>=3.5.0"
        )

    now = datetime.now(tz=timezone.utc)

    with InfluxDBClient(url=url, token=token, org=org) as client:
        write_api = client.write_api(write_options=SYNCHRONOUS)
        points = _build_points(metrics, run_label, now)
        write_api.write(bucket=bucket, org=org, record=points)


def _build_points(metrics: dict, run_label: str, ts: datetime) -> list:
    """Convert the metrics dict into a list of InfluxDB Point objects."""
    try:
        from influxdb_client import Point
    except ImportError:
        raise ImportError("influxdb-client is required.")

    points = []
    for endpoint, m in metrics.items():
        p = (
            Point("endpoint_performance")
            .tag("run", run_label)
            .tag("endpoint", endpoint)
            .field("avg_ms",       float(m.get("avg_ms", 0)))
            .field("p50_ms",       float(m.get("p50_ms", 0)))
            .field("p90_ms",       float(m.get("p90_ms", 0)))
            .field("p95_ms",       float(m.get("p95_ms", 0)))
            .field("p99_ms",       float(m.get("p99_ms", 0)))
            .field("error_rate",   float(m.get("error_rate", 0)))
            .field("throughput",   float(m.get("throughput_rps", 0)))
            .field("samples",      int(m.get("samples", 0)))
            .time(ts)
        )
        points.append(p)
    return points
