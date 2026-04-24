# ⚡ PerfAI — AI-Powered JMeter Script Generator & Performance Analyser


## What It Does

PerfAI combines **performance engineering expertise** with **Azure OpenAI** to automate your entire load testing workflow:

1. **Generate** — Paste a Swagger URL, upload an OpenAPI file, GraphQL schema, or gRPC proto → get a production-ready load test script in JMeter, Gatling, or k6
2. **Run** — Execute the test locally, spin up an AWS EC2 instance, or run distributed across multiple agents
3. **Analyse** — AI reads your `.jtl` results and identifies bottlenecks, root causes, and fixes
4. **Report** — Get a full interactive dashboard + downloadable PDF report with charts, metrics tables, and AI findings
5. **Compare** — Upload 2+ `.jtl` files to compare performance across runs side-by-side
6. **Export & Notify** — Push metrics to InfluxDB/Grafana, send Slack/Teams alerts, schedule recurring runs

## Architecture

```
[Swagger / OpenAPI / GraphQL / gRPC / Plain English]
        ↓
  swagger_parser.py / graphql_parser.py  →  API endpoint/operation list
        ↓
 script_generator.py  →  Azure OpenAI API  →  JMX / Gatling / k6 script
        ↓
   jmeter_runner.py  →  JMeter CLI / AWS EC2 / Distributed  →  results (.jtl)
        ↓
  results_parser.py  →  metrics dict (avg, p50–p99, throughput, errors per endpoint)
        ↓
    ai_analyser.py   →  Azure OpenAI API  →  bottlenecks + recommendations
        ↓
 report_generator.py →  Streamlit dashboard + PDF report
        ↓
 influxdb_writer.py / notifier.py / scheduler.py  →  export / notify / schedule
```

## Quick Start

```bash
# 1. Clone the repo
git clone https://github.com/sabhyata1402/PerfAI-JMeter-Script-Generator-Analyser.git
cd PerfAI-JMeter-Script-Generator-Analyser

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set your credentials
cp .env.example .env
# Edit .env and fill in your Azure OpenAI values

# 4. Run the app
streamlit run app.py
```

## Try It Without JMeter

No JMeter installed? No problem. Use the included sample `.jtl` file to test the full AI analysis and reporting pipeline immediately:

1. Open the **Run & Analyse** tab
2. Select **"Upload existing .jtl results"**
3. Click **"Use sample data"**
4. Click **"Analyse Results with AI"**

## Features

| Feature | Description |
|---|---|
| Swagger / OpenAPI parser | Reads OpenAPI 2.0 and 3.x specs from URL or uploaded file |
| GraphQL support | Introspection query or SDL `.graphql` file → operations list |
| gRPC support | `.proto` file parser → service/method list |
| Plain English input | Describe your API in words — the model infers endpoints and flow |
| JMX generation | Production-grade scripts with auth, timers, assertions, and listeners |
| Gatling generation | Scala simulation via Azure OpenAI — stages, pauses, assertions |
| k6 generation | JavaScript test script via Azure OpenAI — stages, checks, thresholds |
| Load test configuration | Virtual users, duration, ramp-up, think time, base URL, auth type |
| Local JMeter runner | Run tests via subprocess, captures results automatically |
| AWS EC2 runner | Auto-provision instance, run test, download results, terminate |
| Distributed JMeter | Multiple EC2 agent nodes + controller — scales load horizontally |
| InfluxDB export | Push per-endpoint metrics to InfluxDB v2 for live Grafana dashboards |
| Slack / Teams notify | Send test completion summary + AI findings to a webhook |
| Scheduled runs | APScheduler cron-based recurring tests while the app is running |
| .jtl parser | Computes avg, p50, p90, p95, p99, throughput, error rates per endpoint |
| Timeline bucketing | 10-second window breakdown for throughput and latency over time |
| AI bottleneck analysis | Identifies root causes — DB pressure, connection pool, N+1 queries, auth |
| Structured findings | Bottleneck / Warning / Strength / Recommendation with severity levels |
| Interactive dashboard | Plotly charts — timeline, latency bar, error rate, latency spread, error pie |
| Compare Results tab | Upload 2+ JTL files, compare KPIs and latency side-by-side with charts |
| PDF export | Full multi-page report with charts, KPI cards, findings, engine health, glossary |
| Credentials security | Azure OpenAI credentials loaded from `.env` only — never shown in UI |

## UI Overview

The app is split into four tabs:

| Tab | What it does |
|---|---|
| 📝 Script Generator | Parse an API spec and generate a load test script via Azure OpenAI |
| 📊 Run & Analyse | Upload a `.jtl` file or run JMeter, then trigger AI analysis |
| 📄 AI Report | Full interactive report — KPIs, charts, findings, next steps, PDF export |
| ⚖ Compare Results | Side-by-side comparison of 2+ test runs |

## Tech Stack

- **Frontend**: Streamlit with custom purple theme CSS
- **AI**: Azure OpenAI (deployment-based, non-streaming)
- **JMeter**: CLI via Python `subprocess`
- **Cloud**: AWS EC2 via `boto3`
- **Charts**: Plotly (interactive dashboard) + Matplotlib (PDF charts)
- **PDF**: ReportLab
- **API Parsing**: `requests` + `PyYAML`
- **Scheduling**: APScheduler
- **Metrics export**: InfluxDB client v2

## Project Structure

```
perfai/
├── app.py                  ← Streamlit app (entry point)
├── CLAUDE.md               ← Guide for Claude Code
├── requirements.txt
├── .env.example
├── src/
│   ├── swagger_parser.py   ← Parses Swagger/OpenAPI specs + gRPC .proto files
│   ├── graphql_parser.py   ← Parses GraphQL (introspection or SDL)
│   ├── script_generator.py ← Generates JMX / Gatling / k6 via Azure OpenAI
│   ├── jmeter_runner.py    ← Runs JMeter locally, on AWS EC2, or distributed
│   ├── results_parser.py   ← Parses .jtl CSV files into metrics
│   ├── ai_analyser.py      ← Sends metrics to Azure OpenAI for analysis
│   ├── report_generator.py ← Builds interactive Plotly charts and PDF report
│   ├── influxdb_writer.py  ← Exports metrics to InfluxDB v2
│   ├── notifier.py         ← Sends Slack / Teams webhook notifications
│   └── scheduler.py        ← APScheduler-based recurring test scheduling
├── sample_data/
│   └── sample_results.jtl  ← Sample JMeter results for testing
└── output/                 ← Generated scripts and reports saved here
```


## PDF Report Contents

The exported PDF mirrors the interactive web report:

1. **Header** — Test name, date, duration, created by
2. **Filters Applied** — Time range, scenarios, locations
3. **KPI Banner** — Max users, throughput, error rate, avg RT, p90 RT, bandwidth
4. **Test Setup Details** — Start/end time, total requests, test type
5. **Timeline Chart** — Users, hits/s, avg response time, errors over time
6. **Engine Health** — Memory, connections, network I/O, CPU (estimated from JTL patterns)
7. **Request Stats** — Per-endpoint table: samples, avg/p90/p95 RT, errors, hits/s
8. **Errors** — Grouped by endpoint label with HTTP response codes
9. **AI Analysis & Findings** — Verdict, finding cards (bottleneck/warning/strength/recommendation)
10. **Recommended Next Steps** — Numbered action items
11. **Glossary** — Throughput, response time, latency, error rate, percentiles
12. **About** — PerfAI description

## Why I Built This

After 11 years as a performance engineer, I've written hundreds of JMeter scripts and spent countless hours writing the same boilerplate — thread groups, HTTP defaults, timers, assertions. This tool automates all of that.

The AI analysis layer is where the real value is. Instead of manually hunting through `.jtl` CSVs to spot patterns, the model identifies bottlenecks, explains likely root causes, and tells you exactly what to fix.

## Contributing

PRs welcome. Areas for improvement:

- Gatling HTML report parsing
- k6 output format support in the results analyser
- gRPC load generation (ghz integration)
- Multi-region distributed tests
- GitHub Actions CI/CD integration
- Custom dashboard themes

## License

MIT
