"""
engine_dispatcher.py
Auto-detects which load-testing tool produced a results file and routes to the right parser.
Keeps app.py engine-agnostic: it always calls parse_any(path) and gets the same metrics dict.
"""

from pathlib import Path


SUPPORTED_ENGINES = ("jmeter", "gatling", "k6", "loadrunner")


def detect_engine(path: str) -> str:
    """
    Best-effort detection from file extension and a peek at the first line.
    Returns one of: "jmeter", "gatling", "k6", "loadrunner".

    Detection rules:
      .jtl                  -> jmeter
      .log                  -> gatling (Gatling simulation.log)
      .json / .ndjson       -> k6
      .csv                  -> peek at the header:
                                 - JMeter signature ("timestamp"+"elapsed") -> jmeter
                                 - LoadRunner signature ("transaction name") -> loadrunner
                                 - otherwise default to jmeter (existing behaviour)
    """
    p = Path(path)
    ext = p.suffix.lower()

    if ext == ".jtl":
        return "jmeter"
    if ext == ".log":
        return "gatling"
    if ext in (".json", ".ndjson"):
        return "k6"

    if ext == ".csv":
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                header = f.readline().strip().lower()
            if "timestamp" in header and "elapsed" in header:
                return "jmeter"
            if "transaction name" in header or "vuser" in header:
                return "loadrunner"
        except OSError:
            pass
        return "jmeter"  # CSV without a clear signature still tries JMeter parser first

    return "jmeter"


def parse_any(path: str, engine: str = None) -> dict:
    """
    Parse a results file from any supported engine and return the standard metrics dict.
    If engine is None, auto-detect from the file extension.
    """
    engine = (engine or detect_engine(path)).lower()

    if engine == "jmeter":
        from src.results_parser import parse_results
        return parse_results(path)
    if engine == "gatling":
        from src.gatling_parser import parse_results
        return parse_results(path)
    if engine == "k6":
        from src.k6_parser import parse_results
        return parse_results(path)
    if engine == "loadrunner":
        from src.loadrunner_parser import parse_results
        return parse_results(path)

    raise ValueError(f"Unsupported engine '{engine}'. Expected one of: {SUPPORTED_ENGINES}")
