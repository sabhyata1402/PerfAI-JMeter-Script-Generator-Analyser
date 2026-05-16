# Changelog

All notable changes to PerfAI are documented here.

The format is loosely based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased] — Multi-engine support: Gatling, k6, and LoadRunner

PerfAI now supports four load-testing engines as peers: **JMeter, Gatling, k6, and LoadRunner**. All four feed the same metrics dict, so the AI analyser, dashboard, PDF report, and Compare tab work identically for any engine.

### Added

- **`src/gatling_parser.py`** — parses Gatling 3.x `simulation.log` (tab-separated REQUEST records) into the standard metrics dict.
- **`src/k6_parser.py`** — parses k6 JSON output (`k6 run --out json=output.json`) into the standard metrics dict. Reads `http_req_duration` Points and uses `status` + `expected_response` tags to determine success.
- **`src/loadrunner_parser.py`** — parses LoadRunner Analysis CSV exports.
  - Supports both **Raw Data export** (full per-transaction rows → full pipeline) and **Transaction Summary export** (aggregated rows → summary-only fallback).
  - Auto-detects which CSV format it received by checking header columns.
- **`src/engine_dispatcher.py`** — one place to auto-detect engine from a results file and route to the right parser. Public functions: `detect_engine(path)`, `parse_any(path, engine=None)`.
- **`src/script_generator.py`** — added `generate_loadrunner_script()` and `_build_loadrunner_prompt()` for VuGen Web/HTTP `Action.c` generation.
- **`sample_data/sample_loadrunner.csv`** — synthetic LoadRunner Analysis Raw Data export (800 rows, 5 endpoints, ~2% error rate) for demo/testing.
- **Script Generator tab** — new **"LoadRunner (.c)"** option in the Script Format dropdown. Generates VuGen `Action.c` and shows a download button. Includes a callout telling the user to paste into a Web/HTTP VuGen project.
- **Run & Analyse tab** — file uploader now accepts `.jtl`, `.csv`, `.log`, and `.json` extensions. After upload, the auto-detected engine is shown in a "detected engine: X" success message, with a dropdown to override (`jmeter` | `gatling` | `k6` | `loadrunner`).
- **Compare Results tab** — same four file types accepted; description updated to reflect cross-engine comparison.
- **Hero pill / sidebar** — engine list updated from "JMeter / Gatling / k6 generation" to "JMeter / Gatling / k6 / LoadRunner generation".
- **README.md** — Architecture diagram, feature table, project-structure tree, and a new **LoadRunner Support** section documenting the workflow (script-gen + CSV import, no runner).

### Changed

- **`src/engine_dispatcher.py`** — `detect_engine()` for `.csv` files now also detects LoadRunner signatures (`"transaction name"` or `"vuser"` in the header), falling back to JMeter when ambiguous.
- **`app.py`** — script-format dropdown extended from 3 to 4 options; download/clear-session logic updated so generating any one script clears the others.

### Not changed (regression-safe)

The following modules were **not touched** during the multi-engine rollout:

- `src/results_parser.py` (JMeter parser — byte-identical)
- `src/jmeter_runner.py`
- `src/ai_analyser.py`
- `src/report_generator.py`
- `src/swagger_parser.py`
- `src/graphql_parser.py`
- `src/influxdb_writer.py`
- `src/notifier.py`
- `src/scheduler.py`

The existing JMeter flow goes through the dispatcher to the unchanged JMeter parser; smoke-tested with `sample_data/sample_results.jtl` (still returns 30 requests across 5 endpoints).

### Limitations

- **LoadRunner**: no runner — by design. LoadRunner Controller is Windows-only and license-gated; users run the test in their existing LoadRunner toolchain and upload the Analysis CSV export. (See README "LoadRunner Support" section.)
- **Gatling / k6**: also no runner. Users execute via their own `mvn gatling:test` / `k6 run` toolchain. Could be added later as `gatling_runner.py` / `k6_runner.py` if there's demand.
- The LoadRunner Summary CSV fallback only produces summary-level metrics (no timeline, no percentile breakdowns). For the full pipeline, export Raw Data instead.

---

## Earlier changes (chronological, this session)

These are smaller fixes made on `main` before the multi-engine work:

| Commit | What it did |
|---|---|
| `4fafd5f` | Add detailed Setup section to README (env vars, demo paths without keys) |
| `51b3c3c` | Pin `streamlit==1.50.0` in `requirements.txt` so local and Streamlit Cloud render identically (local Python 3.9 caps Streamlit at 1.50.0) |
| `106de2c` | Preserve Material Icons font on icon spans — fixes the visible overlap of icon names ("upload", "light_mode", "dark_mode", "contrast") that occurred because the global font-family override was clobbering Streamlit's icon font |
| `8c014e3` | Remove conflicting custom file_uploader CSS so Streamlit's native button label renders cleanly |
| `7c33ad9` | Enhance README with project overview image and feature pills |
| `a1c7f0a` | Fix overlapping text on file uploader buttons (removed the `::before` pseudo-element that was injecting a duplicate "Upload" label on top of Streamlit's native button text) |
