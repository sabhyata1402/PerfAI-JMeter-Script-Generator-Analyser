"""
app.py — PerfAI: AI-Powered JMeter Script Generator & Performance Analyser
Run with: streamlit run app.py
"""

import streamlit as st
import os
import json
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()


def _validate_generated_jmx(xml_text: str) -> None:
    """Fail fast if model output is not complete well-formed JMX."""
    if not xml_text or not xml_text.startswith("<?xml"):
        raise ValueError("Generated output is missing XML declaration.")
    if not xml_text.strip().endswith("</jmeterTestPlan>"):
        raise ValueError("Generated JMX appears truncated (missing </jmeterTestPlan>).")
    ET.fromstring(xml_text)


def _format_percent(value) -> str:
    try:
        return f"{float(value):.2f}%"
    except Exception:
        return "n/a"


def _severity_rank(severity: str | None) -> int:
    return {"high": 0, "medium": 1, "low": 2}.get((severity or "").lower(), 3)


def _build_report_insights(metrics: dict, analysis: dict) -> dict:
    summary = metrics.get("summary", {})
    endpoints = metrics.get("endpoints", {})
    findings = analysis.get("findings", [])

    slowest_endpoint = None
    if endpoints:
        slowest_endpoint = max(endpoints.items(), key=lambda item: item[1].get("p95_ms", 0))

    worst_error_endpoint = None
    if endpoints:
        worst_error_endpoint = max(endpoints.items(), key=lambda item: item[1].get("error_rate_pct", 0))

    bottlenecks = [f for f in findings if f.get("type") == "bottleneck"]
    recommendations = [f for f in findings if f.get("type") == "recommendation"]
    strengths = [f for f in findings if f.get("type") == "strength"]
    warnings = [f for f in findings if f.get("type") == "warning"]

    risk_level = "Low"
    if summary.get("error_rate_pct", 0) >= 5 or summary.get("p99_ms", 0) >= 3000:
        risk_level = "High"
    elif summary.get("error_rate_pct", 0) >= 1 or summary.get("p99_ms", 0) >= 1500:
        risk_level = "Medium"

    root_causes = Counter()
    for finding in bottlenecks:
        title = str(finding.get("title", "")).lower()
        description = str(finding.get("description", "")).lower()
        text = f"{title} {description}"
        if any(term in text for term in ["database", "db", "sql", "query"]):
            root_causes["Database pressure"] += 1
        if any(term in text for term in ["connection pool", "pool"]):
            root_causes["Connection pool saturation"] += 1
        if any(term in text for term in ["auth", "token", "jwt"]):
            root_causes["Authentication flow"] += 1
        if any(term in text for term in ["n+1", "n1", "multiple calls"]):
            root_causes["Chatty backend / N+1 access"] += 1
        if any(term in text for term in ["cache"]):
            root_causes["Cache inefficiency"] += 1

    if not root_causes and bottlenecks:
        root_causes["Application or dependency bottleneck"] += len(bottlenecks)

    key_observations = []
    if summary:
        key_observations.append(
            f"{summary.get('total_requests', 0):,} requests completed at {summary.get('throughput_rps', 0)} req/s with {_format_percent(summary.get('error_rate_pct', 0))} errors."
        )
        key_observations.append(
            f"Latency distribution: avg {summary.get('avg_ms', 'n/a')} ms, p95 {summary.get('p95_ms', 'n/a')} ms, p99 {summary.get('p99_ms', 'n/a')} ms."
        )
    if slowest_endpoint:
        key_observations.append(
            f"Slowest endpoint by p95 is {slowest_endpoint[0]} at {slowest_endpoint[1].get('p95_ms', 'n/a')} ms."
        )
    if worst_error_endpoint:
        key_observations.append(
            f"Highest error rate is {worst_error_endpoint[0]} at {_format_percent(worst_error_endpoint[1].get('error_rate_pct', 0))}."
        )

    top_findings = sorted(findings, key=lambda f: _severity_rank(f.get("severity")))

    return {
        "risk_level": risk_level,
        "slowest_endpoint": slowest_endpoint,
        "worst_error_endpoint": worst_error_endpoint,
        "bottlenecks": bottlenecks,
        "recommendations": recommendations,
        "strengths": strengths,
        "warnings": warnings,
        "root_causes": root_causes,
        "key_observations": key_observations,
        "top_findings": top_findings,
    }

# ── Page config (must be first Streamlit call) ─────────────────────────────────
st.set_page_config(
    page_title="PerfAI",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ─────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    /* ══ PERFAI — PURPLE THEME ══════════════════════════════════════════════ */

    /* Global font override — clean Inter-style system font */
    html, body, [class*="css"], .stApp, .stMarkdown, p, div, span, label,
    .stTextInput, .stTextArea, .stSelectbox, .stRadio, .stSlider {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif !important;
    }
    /* Tone down Streamlit's default bold headings */
    h1, h2, h3 {
        font-weight: 700 !important;
        color: #1E1B4B !important;
        letter-spacing: -0.02em !important;
    }

    :root {
        --p-purple:     #7C3AED;
        --p-purple-mid: #A78BFA;
        --p-purple-lite:#EDE9FE;
        --p-dark:       #0F172A;
        --p-text:       #1E293B;
        --p-muted:      #64748B;
        --p-border:     #E2E8F0;
        --p-surface:    #FFFFFF;
        --p-bg:         #FAF9FF;
        --p-green:      #059669;
        --p-red:        #DC2626;
        --p-amber:      #D97706;
    }

    /* Background */
    .stApp {
        background: linear-gradient(160deg, #FAF9FF 0%, #F5F3FF 50%, #FAFAFF 100%);
    }
    .block-container { padding-top: 1.2rem; padding-bottom: 2.5rem; }

    /* ── Sidebar ── */
    .stSidebar > div {
        background: linear-gradient(180deg, #1E1B4B 0%, #0F0E2E 100%);
    }
    /* All sidebar text white */
    .stSidebar,
    .stSidebar p, .stSidebar span, .stSidebar div,
    .stSidebar label, .stSidebar [data-testid="stMarkdownContainer"],
    .stSidebar [data-testid="stMarkdownContainer"] p,
    .stSidebar .stSelectbox label,
    .stSidebar h1, .stSidebar h2, .stSidebar h3 {
        color: #FFFFFF !important;
    }
    .stSidebar [data-testid="stMarkdownContainer"] a { color: #C4B5FD !important; }

    /* ── Hero ── */
    .hero-shell {
        background: linear-gradient(135deg, #FFFFFF 0%, #F5F3FF 60%, #EDE9FE 100%);
        border: 1.5px solid #C4B5FD;
        border-radius: 24px;
        padding: 28px 32px;
        box-shadow: 0 4px 24px rgba(124,58,237,0.10), 0 1px 4px rgba(0,0,0,0.04);
        margin-bottom: 20px;
    }
    .hero-kicker {
        font-size: 0.75rem; font-weight: 700;
        letter-spacing: 0.14em; text-transform: uppercase;
        color: var(--p-purple); margin-bottom: 10px;
    }
    .hero-title {
        font-size: 2.2rem; line-height: 1.1; font-weight: 800;
        color: var(--p-dark); margin-bottom: 10px;
    }
    .hero-subtitle { max-width: 820px; color: #475569; line-height: 1.7; font-size: 0.97rem; }
    .hero-pills { margin-top: 16px; display: flex; flex-wrap: wrap; gap: 8px; }
    .hero-pill {
        border-radius: 999px; background: #FFFFFF;
        border: 1.5px solid #DDD6FE; padding: 5px 13px;
        font-size: 0.82rem; font-weight: 600; color: #5B21B6;
    }

    /* ── Tabs ── */
    .stTabs [data-baseweb="tab-list"] {
        gap: 6px; background: #FFFFFF; border-radius: 12px; padding: 4px;
        border: 1.5px solid #DDD6FE;
        box-shadow: 0 1px 8px rgba(124,58,237,0.08);
    }
    .stTabs [data-baseweb="tab"] {
        padding: 9px 20px; font-weight: 600; border-radius: 8px;
        color: var(--p-muted); font-size: 0.9rem;
    }
    .stTabs [aria-selected="true"] {
        background: linear-gradient(135deg, #7C3AED, #A78BFA) !important;
        color: #FFFFFF !important;
        box-shadow: 0 2px 12px rgba(124,58,237,0.35) !important;
    }

    /* ── Buttons ── */
    .stButton > button {
        border-radius: 10px !important;
        background: linear-gradient(135deg, #7C3AED, #A78BFA) !important;
        color: #FFFFFF !important; font-weight: 700 !important; border: none !important;
        padding: 0.55rem 1.4rem !important;
        box-shadow: 0 2px 12px rgba(124,58,237,0.28) !important;
        transition: all 0.15s ease !important;
    }
    .stButton > button:hover {
        opacity: 0.9 !important;
        box-shadow: 0 4px 20px rgba(124,58,237,0.42) !important;
        transform: translateY(-1px) !important;
    }
    .stButton > button[kind="secondary"] {
        background: #FFFFFF !important; color: var(--p-text) !important;
        border: 1.5px solid #DDD6FE !important;
        box-shadow: 0 1px 4px rgba(124,58,237,0.06) !important;
    }

    /* ── Inputs ── */
    .stTextInput input, .stTextArea textarea, .stSelectbox > div > div {
        border: 1.5px solid #DDD6FE !important;
        border-radius: 9px !important; background: #FFFFFF !important;
        color: var(--p-text) !important;
    }
    .stTextInput input:focus, .stTextArea textarea:focus {
        border-color: var(--p-purple) !important;
        box-shadow: 0 0 0 3px rgba(124,58,237,0.14) !important;
    }

    /* ── Dividers ── */
    hr { border-color: #DDD6FE !important; }

    /* ── Verdict labels ── */
    .verdict-pass    { color: #059669; font-weight: 700; font-size: 18px; }
    .verdict-warning { color: #D97706; font-weight: 700; font-size: 18px; }
    .verdict-fail    { color: #DC2626; font-weight: 700; font-size: 18px; }

    /* ── Finding cards ── */
    .finding-card {
        border-left: 4px solid; padding: 14px 18px; margin: 10px 0;
        border-radius: 0 12px 12px 0;
    }
    .finding-bottleneck    { border-color: #DC2626; background: #FEF2F2; }
    .finding-warning       { border-color: #D97706; background: #FFFBEB; }
    .finding-strength      { border-color: #059669; background: #ECFDF5; }
    .finding-recommendation{ border-color: #7C3AED; background: #F5F3FF; }

    /* ── DataFrames ── */
    .stDataFrame, .stTable {
        border-radius: 12px !important; overflow: hidden !important;
        border: 1.5px solid #DDD6FE !important;
        box-shadow: 0 1px 8px rgba(124,58,237,0.07) !important;
    }

    /* ── Scrollbars ── */
    ::-webkit-scrollbar { width: 6px; height: 6px; }
    ::-webkit-scrollbar-track { background: #F5F3FF; }
    ::-webkit-scrollbar-thumb { background: #C4B5FD; border-radius: 3px; }
    ::-webkit-scrollbar-thumb:hover { background: #A78BFA; }

    /* ── Plotly chart card style ── */
    [data-testid="stPlotlyChart"] {
        background: #FFFFFF !important;
        border: 1.5px solid #DDD6FE !important;
        border-radius: 14px !important;
        padding: 12px 8px 4px 8px !important;
        box-shadow: 0 2px 14px rgba(124,58,237,0.09), 0 1px 3px rgba(0,0,0,0.04) !important;
        margin-bottom: 4px !important;
    }

    /* ── Info/warning boxes ── */
    .stAlert { border-radius: 10px !important; }
    [data-testid="stInfo"] {
        border-color: #A78BFA !important;
        background-color: #F5F3FF !important;
    }

    /* ── Top toolbar — matches page background, no border ── */
    header[data-testid="stHeader"] {
        background: #FAF9FF !important;
        box-shadow: none !important;
        border-bottom: none !important;
    }
    [data-testid="stDecoration"] {
        display: none !important;
    }
    /* Push main content below the toolbar height */
    .block-container {
        padding-top: 3.5rem !important;
    }
    /* ── Toolbar dropdown menu — solid opaque background ── */
    [data-testid="stMainMenu"] ul,
    div[role="menu"],
    div[data-baseweb="popover"] > div,
    div[data-baseweb="menu"] {
        background: #FFFFFF !important;
        backdrop-filter: none !important;
        opacity: 1 !important;
    }
</style>
""", unsafe_allow_html=True)

st.markdown(
    """
    <div class="hero-shell">
        <div class="hero-kicker">PerfAI &mdash; Performance Intelligence Platform</div>
        <div class="hero-title">AI-Powered Load Testing<br>&amp; Performance Analysis</div>
        <div class="hero-subtitle">
            Paste an OpenAPI spec or describe your API in plain English. PerfAI uses Azure OpenAI to generate
            a production-ready JMeter plan, run the test, and deliver a detailed report with bottleneck detection,
            root cause analysis, and prioritised fix recommendations.
        </div>
        <div class="hero-pills">
            <span class="hero-pill">⚙ Swagger / OpenAPI / GraphQL / gRPC</span>
            <span class="hero-pill">🤖 JMeter / Gatling / k6 generation</span>
            <span class="hero-pill">📊 .jtl metrics analysis</span>
            <span class="hero-pill">🔍 AI bottleneck detection</span>
            <span class="hero-pill">📄 PDF performance report</span>
            <span class="hero-pill">☁ AWS EC2 &amp; Distributed runs</span>
            <span class="hero-pill">📈 InfluxDB / Grafana export</span>
            <span class="hero-pill">🔔 Slack / Teams notifications</span>
            <span class="hero-pill">🕐 Scheduled recurring tests</span>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div style="padding:12px 0 8px 0;">
        <div style="font-size:1.5rem;font-weight:900;background:linear-gradient(135deg,#A78BFA,#7C3AED);-webkit-background-clip:text;-webkit-text-fill-color:transparent;">⚡ PerfAI</div>
        <div style="font-size:0.78rem;color:#C4B5FD;margin-top:2px;font-weight:500;">AI-Powered Performance Intelligence</div>
    </div>
    """, unsafe_allow_html=True)
    st.divider()

    # Credentials are loaded from environment/.env only — never exposed in UI
    _cfg_key        = bool(os.environ.get("AZURE_OPENAI_API_KEY"))
    _cfg_endpoint   = bool(os.environ.get("AZURE_OPENAI_ENDPOINT"))
    _cfg_deployment = bool(os.environ.get("AZURE_OPENAI_DEPLOYMENT"))
    _cfg_ok = _cfg_key and _cfg_endpoint and _cfg_deployment

    _status_color  = "#059669" if _cfg_ok else "#D97706"
    _status_icon   = "●" if _cfg_ok else "●"
    _status_label  = "Connected" if _cfg_ok else "Not configured"

    st.markdown(
        f"""
        <div style="font-size:0.75rem;font-weight:700;color:#C4B5FD;text-transform:uppercase;
                    letter-spacing:0.12em;margin-bottom:10px;">Azure OpenAI</div>
        <div style="background:rgba(255,255,255,0.07);border:1px solid rgba(196,181,253,0.3);
                    border-radius:10px;padding:12px 14px;">
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
                <span style="color:{_status_color};font-size:1rem;">{_status_icon}</span>
                <span style="color:#FFFFFF;font-size:0.88rem;font-weight:600;">{_status_label}</span>
            </div>
            <div style="font-size:0.78rem;color:#E2E8F0;line-height:1.7;">
                <span style="color:{'#4ADE80' if _cfg_key else '#F87171'};">{'✔' if _cfg_key else '✘'}</span>
                &nbsp;API Key&nbsp;&nbsp;
                <span style="color:{'#4ADE80' if _cfg_endpoint else '#F87171'};">{'✔' if _cfg_endpoint else '✘'}</span>
                &nbsp;Endpoint&nbsp;&nbsp;
                <span style="color:{'#4ADE80' if _cfg_deployment else '#F87171'};">{'✔' if _cfg_deployment else '✘'}</span>
                &nbsp;Deployment
            </div>
            {"" if _cfg_ok else '<div style="margin-top:8px;font-size:0.76rem;color:#FCD34D;font-weight:600;">Set credentials in .env or environment variables.</div>'}
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.divider()
    st.markdown("""
    <div style="font-size:0.75rem;font-weight:700;color:#C4B5FD;text-transform:uppercase;letter-spacing:0.12em;margin-bottom:10px;">About</div>
    <div style="font-size:0.85rem;color:#A78BFA;line-height:1.65;">
    Built by a performance engineer with 11 years of experience.<br><br>
    Azure OpenAI powers:<br>
    <span style="color:#A78BFA;">▸</span> Swagger / GraphQL / gRPC parsing<br>
    <span style="color:#A78BFA;">▸</span> JMeter / Gatling / k6 generation<br>
    <span style="color:#C4B5FD;">▸</span> Results analysis &amp; diagnosis<br>
    <span style="color:#C4B5FD;">▸</span> Fix recommendations<br><br>
    Also ships:<br>
    <span style="color:#A78BFA;">▸</span> Distributed EC2 test runs<br>
    <span style="color:#A78BFA;">▸</span> InfluxDB / Grafana export<br>
    <span style="color:#C4B5FD;">▸</span> Slack / Teams notifications<br>
    <span style="color:#C4B5FD;">▸</span> Scheduled recurring tests<br>
    </div>
    """, unsafe_allow_html=True)
    st.divider()
    st.markdown('<div style="font-size:0.8rem;color:#7C6FAA;text-align:center;"><a href="https://github.com/yourusername/perfai" style="color:#A78BFA;text-decoration:none;">GitHub</a> · Built with Azure OpenAI</div>', unsafe_allow_html=True)

# ── Auto-switch to AI Report tab when requested ────────────────────────────────
if st.session_state.pop("goto_ai_report", False):
    import streamlit.components.v1 as _stc
    _stc.html("""
    <script>
        (function tryClick(attempt) {
            var tabs = window.parent.document.querySelectorAll('[data-baseweb="tab"]');
            if (tabs && tabs.length >= 3) {
                tabs[2].click();
            } else if (attempt < 20) {
                setTimeout(function(){ tryClick(attempt + 1); }, 150);
            }
        })(0);
    </script>
    """, height=0)

# ── Main tabs ──────────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs(["📝 Script Generator", "📊 Run & Analyse", "📄 AI Report", "⚖ Compare Results"])


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Script Generator
# ═══════════════════════════════════════════════════════════════════════════════
with tab1:
    st.markdown("""
    <div style="margin-bottom:18px;">
        <div style="font-size:1.6rem;font-weight:800;color:#1E1B4B;margin-bottom:6px;">JMeter Script Generator</div>
        <div style="font-size:0.95rem;color:#6D28D9;">Generate a production-ready JMeter <code>.jmx</code> script from your API spec or a plain-English description.</div>
    </div>
    """, unsafe_allow_html=True)

    # ── Input method ─────────────────────────────────────────────────────────
    input_method = st.radio(
        "Input method",
        [
            "Swagger / OpenAPI URL",
            "Upload Swagger file",
            "GraphQL (introspection URL)",
            "GraphQL (.graphql SDL file)",
            "gRPC (.proto file)",
            "Describe in plain English",
        ],
        horizontal=True,
    )

    endpoints_text = ""

    if input_method == "Swagger / OpenAPI URL":
        col1, col2 = st.columns([3, 1])
        with col1:
            swagger_url = st.text_input("Swagger / OpenAPI URL", placeholder="https://api.example.com/v3/openapi.json")
        with col2:
            st.markdown("<br>", unsafe_allow_html=True)
            parse_btn = st.button("Parse spec", type="secondary", use_container_width=True)

        if parse_btn and swagger_url:
            with st.spinner("Fetching and parsing Swagger spec..."):
                try:
                    from src.swagger_parser import parse_swagger, endpoints_to_plain_text
                    endpoints = parse_swagger(swagger_url)
                    endpoints_text = endpoints_to_plain_text(endpoints)
                    st.session_state["endpoints_text"] = endpoints_text
                    st.success(f"Found {len(endpoints)} endpoints")
                    with st.expander("Detected endpoints"):
                        for ep in endpoints:
                            st.code(f"{ep['method']:6} {ep['path']}")
                except Exception as e:
                    st.error(f"Failed to parse spec: {e}")

    elif input_method == "Upload Swagger file":
        uploaded = st.file_uploader("Upload your openapi.json or openapi.yaml", type=["json", "yaml", "yml"])
        if uploaded:
            with st.spinner("Parsing..."):
                try:
                    from src.swagger_parser import parse_swagger, endpoints_to_plain_text
                    import yaml, json as json_lib
                    content = uploaded.read()
                    if uploaded.name.endswith((".yaml", ".yml")):
                        spec = yaml.safe_load(content)
                    else:
                        spec = json_lib.loads(content)
                    endpoints = parse_swagger(spec)
                    endpoints_text = endpoints_to_plain_text(endpoints)
                    st.session_state["endpoints_text"] = endpoints_text
                    st.success(f"Found {len(endpoints)} endpoints")
                except Exception as e:
                    st.error(f"Parse error: {e}")

    elif input_method == "GraphQL (introspection URL)":
        col1, col2 = st.columns([3, 1])
        with col1:
            gql_url = st.text_input("GraphQL endpoint URL", placeholder="https://api.example.com/graphql")
        with col2:
            st.markdown("<br>", unsafe_allow_html=True)
            gql_parse_btn = st.button("Introspect schema", type="secondary", use_container_width=True)

        if gql_parse_btn and gql_url:
            with st.spinner("Running introspection query..."):
                try:
                    from src.graphql_parser import parse_graphql_introspection, graphql_operations_to_plain_text
                    ops = parse_graphql_introspection(gql_url)
                    endpoints_text = graphql_operations_to_plain_text(ops)
                    st.session_state["endpoints_text"] = endpoints_text
                    st.success(f"Found {len(ops)} operations")
                    with st.expander("Detected operations"):
                        for op in ops:
                            st.code(f"{op['operation_type'].upper():12} {op['name']}")
                except Exception as e:
                    st.error(f"GraphQL introspection failed: {e}")

    elif input_method == "GraphQL (.graphql SDL file)":
        gql_file = st.file_uploader("Upload your .graphql SDL schema file", type=["graphql", "gql"])
        if gql_file:
            with st.spinner("Parsing SDL schema..."):
                try:
                    from src.graphql_parser import parse_graphql_schema, graphql_operations_to_plain_text
                    schema_text = gql_file.read().decode("utf-8")
                    ops = parse_graphql_schema(schema_text)
                    endpoints_text = graphql_operations_to_plain_text(ops)
                    st.session_state["endpoints_text"] = endpoints_text
                    st.success(f"Found {len(ops)} operations")
                    with st.expander("Detected operations"):
                        for op in ops:
                            st.code(f"{op['operation_type'].upper():12} {op['name']}")
                except Exception as e:
                    st.error(f"SDL parse error: {e}")

    elif input_method == "gRPC (.proto file)":
        proto_file = st.file_uploader("Upload your .proto file", type=["proto"])
        if proto_file:
            with st.spinner("Parsing proto schema..."):
                try:
                    from src.swagger_parser import parse_proto, proto_to_plain_text
                    proto_text = proto_file.read().decode("utf-8")
                    services = parse_proto(proto_text)
                    endpoints_text = proto_to_plain_text(services)
                    st.session_state["endpoints_text"] = endpoints_text
                    st.success(f"Found {len(services)} RPC methods")
                    with st.expander("Detected RPC methods"):
                        for svc in services:
                            streaming = " [streaming]" if svc.get("client_streaming") or svc.get("server_streaming") else ""
                            st.code(f"{svc['service']}.{svc['method']}{streaming}")
                except Exception as e:
                    st.error(f"Proto parse error: {e}")

    else:  # Plain English
        endpoints_text = st.text_area(
            "Describe your API",
            placeholder="""Example:
I have a REST API with these endpoints:
- POST /auth/login — user login with email and password
- GET /users/{id} — get user profile (requires Bearer token)
- GET /products — list all products with pagination
- POST /orders — create a new order (requires auth)
- DELETE /orders/{id} — cancel an order""",
            height=180,
        )
        st.session_state["endpoints_text"] = endpoints_text

    # Restore from session state if already parsed
    if not endpoints_text:
        endpoints_text = st.session_state.get("endpoints_text", "")

    # ── Load test config ──────────────────────────────────────────────────────
    st.divider()
    st.markdown('<div style="font-size:1.1rem;font-weight:700;color:#1E1B4B;margin-bottom:4px;">Load test configuration</div>', unsafe_allow_html=True)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        virtual_users = st.slider("Virtual users", 10, 500, 100, 10)
    with col2:
        duration = st.slider("Duration (minutes)", 1, 30, 5)
    with col3:
        ramp_up = st.slider("Ramp-up (seconds)", 10, 300, 60, 10)
    with col4:
        think_time = st.slider("Think time (ms)", 0, 3000, 500, 100)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        base_url = st.text_input("Base URL", placeholder="https://api.example.com")
    with col2:
        auth_type = st.selectbox("Authentication", ["None", "Bearer Token", "Basic Auth"])
    with col3:
        protocol = st.selectbox("Protocol", ["HTTPS", "HTTP"])
    with col4:
        script_format = st.selectbox("Script Format", ["JMeter (.jmx)", "Gatling (.scala)", "k6 (.js)"])

    # ── Generate button ───────────────────────────────────────────────────────
    st.divider()
    _gen_label = {"JMeter (.jmx)": "⚡ Generate JMeter Script", "Gatling (.scala)": "⚡ Generate Gatling Script", "k6 (.js)": "⚡ Generate k6 Script"}.get(script_format, "⚡ Generate Script")
    if st.button(_gen_label, type="primary", disabled=not endpoints_text):
        if not all([
            os.environ.get("AZURE_OPENAI_API_KEY"),
            os.environ.get("AZURE_OPENAI_ENDPOINT"),
            os.environ.get("AZURE_OPENAI_DEPLOYMENT"),
        ]):
            st.error("Please enter Azure OpenAI key, endpoint, and deployment in the sidebar first.")
        else:
            config = {
                "virtual_users":    virtual_users,
                "duration_seconds": duration * 60,
                "ramp_up_seconds":  ramp_up,
                "think_time_ms":    think_time,
                "base_url":         base_url or "https://api.example.com",
                "auth_type":        auth_type.lower().replace(" ", "_"),
            }
            if script_format == "JMeter (.jmx)":
                with st.spinner("Azure OpenAI is writing your JMeter script..."):
                    try:
                        from src.script_generator import generate_script
                        jmx_script = generate_script(endpoints_text, config)
                        _validate_generated_jmx(jmx_script)
                        st.session_state["jmx_script"] = jmx_script
                        st.session_state.pop("gatling_script", None)
                        st.session_state.pop("k6_script", None)
                        os.makedirs("output", exist_ok=True)
                        jmx_path = "output/generated_test.jmx"
                        with open(jmx_path, "w") as f:
                            f.write(jmx_script)
                        st.session_state["jmx_path"] = jmx_path
                        st.success("JMeter script generated successfully!")
                    except Exception as e:
                        st.session_state.pop("jmx_script", None)
                        st.session_state.pop("jmx_path", None)
                        st.error(f"Generation failed: {e}")

            elif script_format == "Gatling (.scala)":
                with st.spinner("Azure OpenAI is writing your Gatling simulation..."):
                    try:
                        from src.script_generator import generate_gatling_script
                        gatling_script = generate_gatling_script(endpoints_text, config)
                        st.session_state["gatling_script"] = gatling_script
                        st.session_state.pop("jmx_script", None)
                        st.session_state.pop("k6_script", None)
                        os.makedirs("output", exist_ok=True)
                        with open("output/generated_simulation.scala", "w") as f:
                            f.write(gatling_script)
                        st.success("Gatling simulation generated successfully!")
                    except Exception as e:
                        st.session_state.pop("gatling_script", None)
                        st.error(f"Generation failed: {e}")

            else:  # k6
                with st.spinner("Azure OpenAI is writing your k6 script..."):
                    try:
                        from src.script_generator import generate_k6_script
                        k6_script = generate_k6_script(endpoints_text, config)
                        st.session_state["k6_script"] = k6_script
                        st.session_state.pop("jmx_script", None)
                        st.session_state.pop("gatling_script", None)
                        os.makedirs("output", exist_ok=True)
                        with open("output/generated_test.js", "w") as f:
                            f.write(k6_script)
                        st.success("k6 script generated successfully!")
                    except Exception as e:
                        st.session_state.pop("k6_script", None)
                        st.error(f"Generation failed: {e}")

    if "jmx_script" in st.session_state:
        with st.expander("View generated JMX script", expanded=True):
            st.code(st.session_state["jmx_script"], language="xml")
        st.download_button(
            "⬇ Download .jmx script",
            data=st.session_state["jmx_script"],
            file_name="perfai_load_test.jmx",
            mime="application/xml",
        )
        st.info("👉 Head to the **Run & Analyse** tab to execute this script and analyse results.")

    if "gatling_script" in st.session_state:
        with st.expander("View generated Gatling simulation", expanded=True):
            st.code(st.session_state["gatling_script"], language="scala")
        st.download_button(
            "⬇ Download Gatling simulation (.scala)",
            data=st.session_state["gatling_script"],
            file_name="PerfAISimulation.scala",
            mime="text/plain",
        )

    if "k6_script" in st.session_state:
        with st.expander("View generated k6 script", expanded=True):
            st.code(st.session_state["k6_script"], language="javascript")
        st.download_button(
            "⬇ Download k6 script (.js)",
            data=st.session_state["k6_script"],
            file_name="perfai_test.js",
            mime="text/plain",
        )


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Run & Analyse
# ═══════════════════════════════════════════════════════════════════════════════
with tab2:
    st.markdown("""
    <div style="margin-bottom:18px;">
        <div style="font-size:1.6rem;font-weight:800;color:#1E1B4B;margin-bottom:6px;">Run Test &amp; Analyse Results</div>
        <div style="font-size:0.95rem;color:#6D28D9;">Upload an existing <code>.jtl</code> file or run JMeter directly, then analyse with AI.</div>
    </div>
    """, unsafe_allow_html=True)

    run_method = st.radio(
        "How would you like to run the test?",
        ["Upload existing .jtl results", "Run JMeter locally", "Run on AWS EC2", "Distributed (AWS Multi-Agent)"],
        horizontal=True,
    )

    jtl_path = None

    # ── Upload .jtl ───────────────────────────────────────────────────────────
    if run_method == "Upload existing .jtl results":
        col1, col2 = st.columns([2, 1])
        with col1:
            jtl_file = st.file_uploader("Upload JMeter .jtl results file", type=["jtl", "csv"])
        with col2:
            st.info("📁 Don't have a .jtl file? Use our sample data to try the analyser.")
            if st.button("Use sample data"):
                jtl_path = "sample_data/sample_results.jtl"
                st.session_state["jtl_path"] = jtl_path
                st.success("Sample data loaded!")

        if jtl_file:
            os.makedirs("output", exist_ok=True)
            jtl_path = "output/uploaded_results.jtl"
            with open(jtl_path, "wb") as f:
                f.write(jtl_file.read())
            st.session_state["jtl_path"] = jtl_path
            st.success("Results file uploaded!")

    # ── Run locally ───────────────────────────────────────────────────────────
    elif run_method == "Run JMeter locally":
        st.info("Requires JMeter to be installed and on your PATH. Set `JMETER_PATH` env var if needed.")
        jmx_path = st.session_state.get("jmx_path", "")
        if not jmx_path:
            st.warning("Generate a JMX script in the Script Generator tab first, or upload one below.")
            jmx_upload = st.file_uploader("Upload .jmx file", type=["jmx"])
            if jmx_upload:
                os.makedirs("output", exist_ok=True)
                jmx_path = "output/uploaded.jmx"
                with open(jmx_path, "wb") as f:
                    f.write(jmx_upload.read())

        if jmx_path and st.button("▶ Run JMeter", type="primary"):
            with st.spinner("Running JMeter... this may take a few minutes"):
                try:
                    from src.jmeter_runner import run_local
                    jtl_path = run_local(jmx_path)
                    st.session_state["jtl_path"] = jtl_path
                    st.success(f"Test complete! Results at: {jtl_path}")
                except Exception as e:
                    st.error(f"JMeter run failed: {e}")

    # ── Run on AWS ────────────────────────────────────────────────────────────
    else:
        st.info("Spins up an EC2 instance, runs the test, downloads results, terminates instance.")
        col1, col2, col3 = st.columns(3)
        with col1:
            aws_region = st.text_input("AWS Region", value="eu-west-1")
        with col2:
            instance_type = st.selectbox("Instance Type", ["t3.medium", "t3.large", "c5.xlarge"])
        with col3:
            key_name = st.text_input("EC2 Key Pair Name", placeholder="my-key-pair")

        if st.button("☁ Run on AWS", type="primary"):
            jmx_path = st.session_state.get("jmx_path")
            if not jmx_path:
                st.error("Generate or upload a JMX script first.")
            else:
                with st.spinner("Provisioning EC2, running test, downloading results..."):
                    try:
                        from src.jmeter_runner import run_on_aws
                        jtl_path = run_on_aws(jmx_path, cfg={
                            "region": aws_region,
                            "instance_type": instance_type,
                            "key_name": key_name,
                        })
                        st.session_state["jtl_path"] = jtl_path
                        st.success("AWS run complete! Results downloaded.")
                    except Exception as e:
                        st.error(f"AWS run failed: {e}")

    # ── Distributed (AWS Multi-Agent) ─────────────────────────────────────────
    if run_method == "Distributed (AWS Multi-Agent)":
        st.info("Spins up multiple EC2 agent instances plus a controller. Each agent drives a share of the load.")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            dist_region = st.text_input("AWS Region", value="eu-west-1", key="dist_region")
        with col2:
            dist_agents = st.number_input("Number of agent nodes", min_value=2, max_value=10, value=2, key="dist_agents")
        with col3:
            dist_agent_type = st.selectbox("Agent instance type", ["t3.large", "c5.xlarge", "c5.2xlarge"], key="dist_agent_type")
        with col4:
            dist_key = st.text_input("EC2 Key Pair Name", placeholder="my-key-pair", key="dist_key")

        if st.button("☁ Run Distributed", type="primary"):
            jmx_path = st.session_state.get("jmx_path")
            if not jmx_path:
                st.error("Generate or upload a JMX script in the Script Generator tab first.")
            else:
                with st.spinner(f"Provisioning {dist_agents} agents + controller, running distributed test..."):
                    try:
                        from src.jmeter_runner import run_distributed
                        jtl_path = run_distributed(jmx_path, cfg={
                            "region":       dist_region,
                            "agent_count":  dist_agents,
                            "agent_type":   dist_agent_type,
                            "key_name":     dist_key,
                        })
                        st.session_state["jtl_path"] = jtl_path
                        st.success("Distributed run complete! Results downloaded.")
                    except Exception as e:
                        st.error(f"Distributed run failed: {e}")

    # ── Parse & Analyse ───────────────────────────────────────────────────────
    st.divider()
    jtl_path = st.session_state.get("jtl_path")

    if jtl_path and os.path.exists(jtl_path):
        st.success(f"Results ready: `{jtl_path}`")

        if st.button("🤖 Analyse Results with AI", type="primary"):
            if not all([
                os.environ.get("AZURE_OPENAI_API_KEY"),
                os.environ.get("AZURE_OPENAI_ENDPOINT"),
                os.environ.get("AZURE_OPENAI_DEPLOYMENT"),
            ]):
                st.error("Please enter Azure OpenAI key, endpoint, and deployment in the sidebar.")
            else:
                with st.spinner("Parsing results..."):
                    from src.results_parser import parse_results
                    metrics = parse_results(jtl_path)
                    st.session_state["metrics"] = metrics

                with st.spinner("Azure OpenAI is analysing your results..."):
                    from src.ai_analyser import analyse
                    analysis = analyse(metrics)
                    st.session_state["analysis"] = analysis

                st.markdown("""
                <div style="background:linear-gradient(135deg,#F5F3FF,#EDE9FE);
                            border:1.5px solid #A78BFA;border-radius:14px;
                            padding:20px 26px;margin-top:14px;
                            box-shadow:0 3px 16px rgba(124,58,237,0.15);">
                    <div style="font-size:1.15rem;font-weight:800;color:#4C1D95;margin-bottom:8px;">
                        ✅ Analysis complete!
                    </div>
                    <div style="font-size:0.92rem;color:#374151;margin-bottom:16px;">
                        Your full performance report is ready. Click the button below to go straight to it.
                    </div>
                </div>
                """, unsafe_allow_html=True)
                if st.button("📄 View AI Report →", type="primary", key="goto_report"):
                    st.session_state["goto_ai_report"] = True
                    st.rerun()

    # ── Post-analysis actions (shown whenever metrics+analysis exist) ──────────
    if st.session_state.get("metrics") and st.session_state.get("analysis"):
        st.divider()
        st.markdown('<div style="font-size:1.05rem;font-weight:700;color:#1E1B4B;margin-bottom:4px;">Post-Analysis Actions</div>', unsafe_allow_html=True)

        # ── Export to InfluxDB ────────────────────────────────────────────────
        with st.expander("📈 Export to InfluxDB / Grafana"):
            st.markdown('<div style="font-size:0.85rem;color:#5B21B6;margin-bottom:10px;">Push metrics to InfluxDB v2 for live Grafana dashboards.</div>', unsafe_allow_html=True)
            col1, col2 = st.columns(2)
            with col1:
                influx_url   = st.text_input("InfluxDB URL",    value="http://localhost:8086", key="influx_url")
                influx_token = st.text_input("API Token",        type="password", key="influx_token")
            with col2:
                influx_org    = st.text_input("Organisation",    value="perfai", key="influx_org")
                influx_bucket = st.text_input("Bucket",          value="perfai", key="influx_bucket")
                run_label_i   = st.text_input("Run Label",       value="perfai_run", key="influx_run_label")

            if st.button("📤 Export to InfluxDB", key="export_influx"):
                with st.spinner("Writing metrics to InfluxDB..."):
                    try:
                        from src.influxdb_writer import write_metrics
                        write_metrics(
                            st.session_state["metrics"]["endpoints"],
                            run_label=run_label_i,
                            url=influx_url,
                            token=influx_token,
                            org=influx_org,
                            bucket=influx_bucket,
                        )
                        st.success("Metrics exported to InfluxDB successfully!")
                    except Exception as e:
                        st.error(f"InfluxDB export failed: {e}")

        # ── Slack / Teams notifications ───────────────────────────────────────
        with st.expander("🔔 Notify via Slack / Teams"):
            st.markdown('<div style="font-size:0.85rem;color:#5B21B6;margin-bottom:10px;">Send a test completion summary to Slack or Microsoft Teams.</div>', unsafe_allow_html=True)
            notif_platform = st.radio("Platform", ["Slack", "Microsoft Teams"], horizontal=True, key="notif_platform")
            webhook_url    = st.text_input("Incoming Webhook URL", type="password", key="notif_webhook")

            _s = st.session_state["metrics"]["summary"]
            default_msg = (
                f"Load test complete. "
                f"Requests: {_s.get('total_requests',0):,} | "
                f"Throughput: {_s.get('throughput_rps',0)} req/s | "
                f"Error rate: {_s.get('error_rate_pct',0):.2f}% | "
                f"P95: {_s.get('p95_ms',0)} ms"
            )
            notif_msg = st.text_area("Message", value=default_msg, key="notif_msg")

            if st.button("Send Notification", key="send_notif"):
                if not webhook_url:
                    st.error("Enter a webhook URL first.")
                else:
                    with st.spinner("Sending notification..."):
                        try:
                            findings = st.session_state["analysis"].get("findings", [])
                            from src.notifier import notify_slack, notify_teams
                            if notif_platform == "Slack":
                                notify_slack(webhook_url, notif_msg, findings)
                            else:
                                notify_teams(webhook_url, notif_msg, findings)
                            st.success(f"{notif_platform} notification sent!")
                        except Exception as e:
                            st.error(f"Notification failed: {e}")

        # ── Schedule recurring runs ───────────────────────────────────────────
        with st.expander("🕐 Schedule Recurring Test Runs"):
            st.markdown('<div style="font-size:0.85rem;color:#5B21B6;margin-bottom:10px;">Schedule this test to run automatically on a cron schedule (while the app is running).</div>', unsafe_allow_html=True)
            col1, col2, col3 = st.columns(3)
            with col1:
                sched_id   = st.text_input("Job ID", value="nightly-load-test", key="sched_id")
            with col2:
                sched_cron = st.text_input("Cron expression (5-field)", value="0 2 * * *", key="sched_cron",
                                           help="minute hour day month weekday — e.g. '0 2 * * *' = every night at 02:00")
            with col3:
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("➕ Add Schedule", key="add_sched"):
                    jmx_p = st.session_state.get("jmx_path")
                    if not jmx_p:
                        st.error("No JMX script in session. Generate one first.")
                    else:
                        try:
                            from src.scheduler import schedule_test
                            from src.jmeter_runner import run_local
                            schedule_test(sched_id, sched_cron, run_local, jmx_p)
                            st.success(f"Scheduled '{sched_id}' with cron: {sched_cron}")
                        except Exception as e:
                            st.error(f"Scheduling failed: {e}")

            if st.button("📋 View scheduled jobs", key="list_sched"):
                try:
                    from src.scheduler import list_jobs
                    jobs = list_jobs()
                    if jobs:
                        import pandas as pd
                        st.dataframe(pd.DataFrame(jobs), use_container_width=True, hide_index=True)
                    else:
                        st.info("No jobs scheduled.")
                except Exception as e:
                    st.error(f"Could not list jobs: {e}")

            col_rm1, col_rm2 = st.columns([2, 1])
            with col_rm1:
                rm_id = st.text_input("Job ID to remove", key="rm_sched_id")
            with col_rm2:
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("🗑 Remove", key="rm_sched"):
                    try:
                        from src.scheduler import remove_job
                        removed = remove_job(rm_id)
                        st.success(f"Removed job '{rm_id}'." if removed else f"Job '{rm_id}' not found.")
                    except Exception as e:
                        st.error(f"Remove failed: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 3 — AI Report  (BlazeMeter-style layout)
# ═══════════════════════════════════════════════════════════════════════════════
with tab3:
    import pandas as pd
    from src.report_generator import build_interactive_charts

    metrics  = st.session_state.get("metrics")
    analysis = st.session_state.get("analysis")

    _report_ready = bool(metrics and analysis)
    if not _report_ready:
        st.markdown("""
        <div style="background:#F5F3FF;border:1.5px solid #DDD6FE;border-radius:14px;
                    padding:40px 32px;text-align:center;margin-top:20px;">
            <div style="font-size:2.5rem;margin-bottom:12px;">📊</div>
            <div style="font-size:1.1rem;font-weight:700;color:#4C1D95;margin-bottom:8px;">
                No report yet
            </div>
            <div style="font-size:0.9rem;color:#6D28D9;">
                Go to the <b>Run &amp; Analyse</b> tab, upload a <code>.jtl</code> file,
                and click <b>Analyse Results with AI</b> to generate your report.
            </div>
        </div>
        """, unsafe_allow_html=True)

    if _report_ready:
        s = metrics["summary"]
        report_insights = _build_report_insights(metrics, analysis)
        # ── All report content lives inside this block ─────────────────────────
        duration_min = round(s["duration_seconds"] / 60, 1)
        test_name    = f"PerfAI Load Test  {datetime.now().strftime('%B_%d_%I:%M %p')}"

        st.markdown(f"""
        <div style="background:linear-gradient(135deg,#FFFFFF 0%,#F5F3FF 60%,#EDE9FE 100%);
                    border:1.5px solid #DDD6FE;border-radius:16px;
                    padding:22px 26px 18px 26px;margin-bottom:0;
                    box-shadow:0 4px 20px rgba(124,58,237,0.12),0 1px 4px rgba(124,58,237,0.06);">
            <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:10px;">
                <div>
                    <div style="font-size:0.75rem;color:#7C3AED;font-weight:700;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:6px;">Load Test Report</div>
                    <div style="font-size:1.5rem;font-weight:800;color:#1E1B4B;">{test_name}</div>
                </div>
                <div style="font-size:0.85rem;color:#4C1D95;line-height:1.9;text-align:right;">
                    <b>Report Created By:</b> PerfAI<br>
                    <b>Date of Run:</b> {datetime.now().strftime("%a, %m/%d/%Y - %H:%M")}<br>
                    <b>Duration:</b> {duration_min} minutes
                </div>
            </div>
        </div>
        <div style="height:3px;background:linear-gradient(90deg,#7C3AED,#A78BFA);border-radius:0 0 6px 6px;margin-bottom:24px;box-shadow:0 2px 8px rgba(124,58,237,0.2);"></div>
        """, unsafe_allow_html=True)

        # ══ FILTERS APPLIED ════════════════════════════════════════════════════════
        def _pill(text):
            return f'<span style="background:#EDE9FE;color:#6D28D9;font-weight:600;font-size:0.8rem;padding:4px 12px;border-radius:6px;border:1px solid #DDD6FE;">{text}</span>'

        time_range = f"{s.get('test_start','—')}  →  {s.get('test_end','—')}"
        st.markdown(f"""
        <div style="background:linear-gradient(135deg,#FFFFFF,#F5F3FF);border:1.5px solid #DDD6FE;
                    border-radius:14px;padding:18px 22px;margin-bottom:20px;
                    box-shadow:0 2px 14px rgba(124,58,237,0.09),0 1px 3px rgba(124,58,237,0.05);">
            <div style="font-size:1rem;font-weight:700;color:#1E1B4B;margin-bottom:14px;">Filters Applied</div>
            <table style="border-collapse:collapse;width:100%;font-size:0.9rem;">
                <tr><td style="padding:7px 12px;width:160px;color:#7C3AED;font-weight:500;">Time Range:</td><td style="padding:7px 0;">{_pill(time_range)}</td></tr>
                <tr><td style="padding:7px 12px;color:#7C3AED;font-weight:500;">Scenarios:</td><td style="padding:7px 0;">{_pill("All")}</td></tr>
                <tr><td style="padding:7px 12px;color:#7C3AED;font-weight:500;">Time Displayed In:</td><td style="padding:7px 0;">{_pill("Milliseconds")}</td></tr>
                <tr><td style="padding:7px 12px;color:#7C3AED;font-weight:500;">Locations:</td><td style="padding:7px 0;">{_pill("All")}</td></tr>
            </table>
        </div>
        """, unsafe_allow_html=True)

        # ══ KPI BANNER ═════════════════════════════════════════════════════════════
        p90_s  = round(s["p90_ms"] / 1000, 2)
        bw     = s.get("avg_bandwidth_kbps", 0)
        bw_str = f"{bw:.2f} KiB/s" if bw else "N/A"
        max_u  = s.get("max_users") or "N/A"
        err_col = "#DC2626" if float(s.get("error_rate_pct",0) or 0) >= 5 else "#D97706" if float(s.get("error_rate_pct",0) or 0) >= 1 else "#111827"

        def _kpi(val, unit, label, val_color="#7C3AED"):
            return f'''<td style="background:linear-gradient(135deg,#FFFFFF,#F5F3FF);
                                 border:1.5px solid #DDD6FE;padding:16px 20px;text-align:left;min-width:110px;
                                 border-radius:12px;box-shadow:0 3px 12px rgba(124,58,237,0.10),0 1px 3px rgba(124,58,237,0.06);">
                <span style="font-size:1.6rem;font-weight:800;color:{val_color};">{val}</span>
                <span style="font-size:0.85rem;color:#6B7280;font-weight:600;"> {unit}</span><br>
                <span style="font-size:0.75rem;color:#9CA3AF;font-weight:500;">{label}</span></td>'''

        st.markdown(f"""
        <table style="border-collapse:separate;border-spacing:8px;width:100%;margin-bottom:20px;">
            <tr>
                {_kpi(max_u, "VU", "Max Users")}
                {_kpi(s["throughput_rps"], "Hits/s", "Avg. Throughput")}
                {_kpi(f"{s['error_rate_pct']:.2f}", "%", "Errors", err_col)}
                {_kpi(f"{s['avg_ms']:.2f}", "ms", "Avg. Response Time")}
                {_kpi(f"{p90_s:.2f}", "s", "90% Response Time")}
                {_kpi(bw_str, "", "Avg. Bandwidth")}
            </tr>
        </table>
        """, unsafe_allow_html=True)

        # ══ TEST SETUP DETAILS ═════════════════════════════════════════════════════
        st.markdown(f"""
        <div style="background:linear-gradient(135deg,#FFFFFF,#F5F3FF);border:1.5px solid #DDD6FE;
                    border-radius:14px;padding:18px 22px;margin-bottom:20px;
                    box-shadow:0 2px 14px rgba(124,58,237,0.09),0 1px 3px rgba(124,58,237,0.05);">
            <div style="font-size:1rem;font-weight:700;color:#1E1B4B;margin-bottom:14px;">Test Setup Details</div>
            <table style="border-collapse:collapse;width:100%;font-size:0.88rem;">
                <tr><td style="padding:7px 0;width:160px;color:#7C3AED;font-weight:500;">Executed By:</td><td style="color:#1E1B4B;font-weight:600;">PerfAI</td></tr>
                <tr><td style="padding:7px 0;color:#7C3AED;font-weight:500;">Test Types:</td><td>{_pill("JMeter")}</td></tr>
                <tr><td style="padding:7px 0;color:#7C3AED;font-weight:500;">Test Started:</td><td style="color:#374151;">{s.get("test_start","—")}</td></tr>
                <tr><td style="padding:7px 0;color:#7C3AED;font-weight:500;">Test Ended:</td><td style="color:#374151;">{s.get("test_end","—")}</td></tr>
                <tr><td style="padding:7px 0;color:#7C3AED;font-weight:500;">Time Elapsed:</td><td style="color:#374151;">{duration_min} minutes</td></tr>
                <tr><td style="padding:7px 0;color:#7C3AED;font-weight:500;">Total Requests:</td><td style="color:#1E1B4B;font-weight:600;">{s["total_requests"]:,}</td></tr>
            </table>
        </div>
        <div style="height:3px;background:linear-gradient(90deg,#7C3AED,#A78BFA);border-radius:3px;margin-bottom:24px;box-shadow:0 2px 8px rgba(124,58,237,0.2);"></div>
        """, unsafe_allow_html=True)

        # ══ TIMELINE ══════════════════════════════════════════════════════════════
        _sec_hdr = lambda title: f'''
        <div style="display:flex;align-items:center;gap:10px;margin:28px 0 6px 0;">
            <div style="width:4px;height:28px;background:#7C3AED;border-radius:2px;"></div>
            <span style="font-size:1.35rem;font-weight:800;color:#111827;">{title}</span>
        </div>
        <div style="height:2px;background:linear-gradient(90deg,#7C3AED 60%,transparent);margin-bottom:16px;border-radius:2px;"></div>
        '''
        charts = build_interactive_charts(metrics)
        _pcfg  = {"scrollZoom": False, "displayModeBar": False, "displaylogo": False}

        st.markdown(_sec_hdr("Timeline"), unsafe_allow_html=True)
        st.markdown(f'<div style="font-size:0.85rem;color:#9CA3AF;margin-bottom:10px;">Chart Resolution: {_pill("Dynamic")}</div>', unsafe_allow_html=True)
        st.markdown('<div style="font-size:1rem;font-weight:700;color:#111827;margin-bottom:6px;">Main Timeline Chart</div>', unsafe_allow_html=True)
        st.plotly_chart(charts["timeline"], use_container_width=True, config=_pcfg)
        st.markdown('<div style="height:4px;"></div>', unsafe_allow_html=True)

        # ══ REQUEST STATS ══════════════════════════════════════════════════════════
        st.markdown(_sec_hdr("Request Stats"), unsafe_allow_html=True)
        n_eps = len(metrics["endpoints"])
        st.markdown(f'<div style="background:#F5F3FF;border:1px solid #DDD6FE;border-radius:8px;padding:8px 14px;font-size:0.85rem;color:#5B21B6;margin-bottom:12px;">ⓘ  Showing {min(n_eps+1,25)} records (including ALL aggregate row).</div>', unsafe_allow_html=True)

        dur = s["duration_seconds"] or 1
        rs_rows = [{"Element Label": "ALL", "# Samples": s["total_requests"],
                    "Avg. Response (ms)": s["avg_ms"], "90% line (ms)": s["p90_ms"],
                    "95% line (ms)": s["p95_ms"], "Error Count": s["error_count"],
                    "Avg. Hits/s": s["throughput_rps"]}]
        for label, ep in list(metrics["endpoints"].items())[:24]:
            rs_rows.append({"Element Label": label, "# Samples": ep["total_requests"],
                            "Avg. Response (ms)": ep["avg_ms"], "90% line (ms)": ep["p90_ms"],
                            "95% line (ms)": ep["p95_ms"], "Error Count": ep["error_count"],
                            "Avg. Hits/s": round(ep["total_requests"] / dur, 2)})
        st.dataframe(pd.DataFrame(rs_rows), use_container_width=True, hide_index=True)

        # ══ LATENCY CHART ═════════════════════════════════════════════════════════
        st.markdown(_sec_hdr("Latency by Endpoint"), unsafe_allow_html=True)
        st.plotly_chart(charts["latency_bar"], use_container_width=True, config=_pcfg)
        st.markdown('<div style="height:4px;"></div>', unsafe_allow_html=True)

        # ══ ERROR RATE CHART ══════════════════════════════════════════════════════
        st.markdown(_sec_hdr("Error Rate by Endpoint"), unsafe_allow_html=True)
        st.plotly_chart(charts["error_rate_bar"], use_container_width=True, config=_pcfg)
        st.markdown('<div style="height:4px;"></div>', unsafe_allow_html=True)

        # ══ LATENCY SPREAD CHART ══════════════════════════════════════════════════
        st.markdown(_sec_hdr("Latency Distribution"), unsafe_allow_html=True)
        st.plotly_chart(charts["latency_spread"], use_container_width=True, config=_pcfg)
        st.markdown('<div style="height:4px;"></div>', unsafe_allow_html=True)

        # ══ ERROR PIE CHART / NO ERRORS ══════════════════════════════════════════
        st.markdown(_sec_hdr("Errors"), unsafe_allow_html=True)
        if metrics.get("errors"):
            st.plotly_chart(charts["error_pie"], use_container_width=True, config=_pcfg)
        else:
            st.markdown("""
            <div style="background:#ECFDF5;border:1.5px solid #6EE7B7;border-radius:14px;
                        padding:28px 24px;text-align:center;margin-bottom:20px;">
                <div style="font-size:2rem;margin-bottom:8px;">✅</div>
                <div style="font-size:1.1rem;font-weight:700;color:#065F46;margin-bottom:4px;">
                    No Errors
                </div>
                <div style="font-size:0.9rem;color:#047857;">
                    There were no errors during the test. All requests completed successfully.
                </div>
            </div>
            """, unsafe_allow_html=True)

        # ══ ERRORS GROUPED BY LABEL ════════════════════════════════════════════════
        errors_by_label = metrics.get("errors_by_label", {})
        if errors_by_label:
            st.markdown('<div style="font-size:0.95rem;font-weight:700;color:#374151;margin-bottom:12px;">Grouped by Label</div>', unsafe_allow_html=True)
            for label, code_list in errors_by_label.items():
                st.markdown(f'<div style="font-size:0.85rem;color:#374151;margin-bottom:6px;">Label: {_pill(label)}</div>', unsafe_allow_html=True)
                st.markdown('<div style="font-size:0.8rem;color:#9CA3AF;margin-bottom:4px;">Response Codes</div>', unsafe_allow_html=True)
                err_df = pd.DataFrame(code_list)[["code","description","count"]]
                err_df.columns = ["Code", "Description", "Count"]
                st.dataframe(err_df, use_container_width=True, hide_index=True)
                st.markdown('<div style="height:10px;"></div>', unsafe_allow_html=True)

        # ══ AI ANALYSIS ════════════════════════════════════════════════════════════
        verdict      = analysis.get("verdict", "warning")
        verdict_icon = {"pass": "✅", "warning": "⚠️", "fail": "❌"}.get(verdict, "⚠️")
        verdict_col  = {"pass": "#059669", "warning": "#D97706", "fail": "#DC2626"}.get(verdict, "#D97706")
        verdict_bg   = {"pass": "linear-gradient(135deg,#ECFDF5,#D1FAE5)",
                        "warning": "linear-gradient(135deg,#FFFBEB,#FEF3C7)",
                        "fail":    "linear-gradient(135deg,#FEF2F2,#FEE2E2)"}.get(verdict, "linear-gradient(135deg,#FFFBEB,#FEF3C7)")
        verdict_border = {"pass": "#6EE7B7", "warning": "#FCD34D", "fail": "#FCA5A5"}.get(verdict, "#FCD34D")

        st.markdown(_sec_hdr("AI Analysis & Findings"), unsafe_allow_html=True)

        # Verdict banner — gradient card style
        st.markdown(f"""
        <div style="background:{verdict_bg};border:1.5px solid {verdict_border};border-radius:14px;
                    padding:16px 22px;margin-bottom:20px;
                    box-shadow:0 2px 14px rgba(0,0,0,0.06),0 1px 3px rgba(0,0,0,0.04);">
            <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
                <span style="font-size:1.5rem;">{verdict_icon}</span>
                <span style="font-size:1rem;font-weight:800;color:{verdict_col};letter-spacing:0.02em;">Verdict: {verdict.upper()}</span>
                <span style="font-size:0.9rem;color:#374151;font-weight:400;">{analysis.get('headline','')}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # Finding type config
        _ftype_cfg = {
            "bottleneck":     {"accent": "#DC2626", "bg": "linear-gradient(135deg,#FFFFFF,#FEF2F2)", "border": "#FECACA", "badge_bg": "#FEE2E2", "label": "BOTTLENECK"},
            "warning":        {"accent": "#D97706", "bg": "linear-gradient(135deg,#FFFFFF,#FFFBEB)", "border": "#FDE68A", "badge_bg": "#FEF3C7", "label": "WARNING"},
            "strength":       {"accent": "#059669", "bg": "linear-gradient(135deg,#FFFFFF,#ECFDF5)", "border": "#6EE7B7", "badge_bg": "#D1FAE5", "label": "STRENGTH"},
            "recommendation": {"accent": "#7C3AED", "bg": "linear-gradient(135deg,#FFFFFF,#F5F3FF)", "border": "#DDD6FE", "badge_bg": "#EDE9FE", "label": "RECOMMENDATION"},
        }
        _sev_colors = {"HIGH": "#DC2626", "MEDIUM": "#D97706", "LOW": "#059669"}

        findings_all = sorted(report_insights["top_findings"], key=lambda f: _severity_rank(f.get("severity")))
        for finding in findings_all:
            ftype = finding.get("type", "recommendation")
            cfg   = _ftype_cfg.get(ftype, _ftype_cfg["recommendation"])
            sev   = (finding.get("severity") or "n/a").upper()
            ep    = finding.get("endpoint") or "General"
            sev_color = _sev_colors.get(sev, "#6B7280")
            st.markdown(f"""
            <div style="background:{cfg['bg']};border:1.5px solid {cfg['border']};border-radius:14px;
                        margin-bottom:10px;overflow:hidden;
                        box-shadow:0 2px 10px rgba(0,0,0,0.05),0 1px 3px rgba(0,0,0,0.03);">
                <div style="height:3px;background:{cfg['accent']};"></div>
                <div style="padding:14px 18px 14px 18px;">
                    <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:8px;margin-bottom:8px;">
                        <div style="display:flex;align-items:center;gap:8px;">
                            <span style="font-size:0.72rem;font-weight:800;letter-spacing:0.08em;
                                         background:{cfg['badge_bg']};color:{cfg['accent']};
                                         padding:3px 9px;border-radius:6px;border:1px solid {cfg['border']};">{cfg['label']}</span>
                            <span style="font-size:0.95rem;font-weight:700;color:#111827;">{finding.get('title','')}</span>
                        </div>
                        <div style="display:flex;gap:6px;flex-shrink:0;">
                            <span style="font-size:0.72rem;font-weight:700;padding:3px 10px;border-radius:6px;
                                         background:#fff;color:{sev_color};border:1px solid {sev_color};">{sev}</span>
                            <span style="font-size:0.72rem;font-weight:600;padding:3px 10px;border-radius:6px;
                                         background:#F5F3FF;color:#5B21B6;border:1px solid #DDD6FE;">{ep}</span>
                        </div>
                    </div>
                    <div style="line-height:1.65;color:#374151;font-size:0.88rem;">{finding.get('description','')}</div>
                </div>
            </div>
            """, unsafe_allow_html=True)

        # ══ NEXT STEPS ════════════════════════════════════════════════════════════
        next_steps = analysis.get("next_steps", [])
        if next_steps:
            st.markdown('<div style="height:8px;"></div>', unsafe_allow_html=True)
            st.markdown("""
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:12px;">
                <div style="width:4px;height:20px;background:#7C3AED;border-radius:2px;"></div>
                <span style="font-size:1rem;font-weight:800;color:#111827;">Recommended Next Steps</span>
            </div>
            """, unsafe_allow_html=True)
            steps_html = ""
            for i, step in enumerate(next_steps, 1):
                bg = "#FFFFFF" if i % 2 == 1 else "#FAFAFA"
                steps_html += (f'<div style="display:flex;gap:14px;align-items:flex-start;padding:12px 16px;border-bottom:1px solid #F3F4F6;background:{bg};">'
                    f'<span style="min-width:26px;height:26px;border-radius:8px;background:linear-gradient(135deg,#7C3AED,#A78BFA);color:#FFFFFF;font-weight:800;font-size:0.8rem;display:flex;align-items:center;justify-content:center;flex-shrink:0;">{i}</span>'
                    f'<span style="color:#374151;font-size:0.9rem;line-height:1.65;padding-top:3px;">{step}</span>'
                    f'</div>')
            st.markdown(f"""
            <div style="background:linear-gradient(135deg,#FFFFFF,#F5F3FF);border:1.5px solid #DDD6FE;
                        border-radius:14px;overflow:hidden;
                        box-shadow:0 2px 14px rgba(124,58,237,0.09),0 1px 3px rgba(124,58,237,0.05);">
                {steps_html}
            </div>
            """, unsafe_allow_html=True)

        st.markdown('<hr style="border:none;border-top:3px solid #7C3AED;margin:20px 0;">', unsafe_allow_html=True)

        # ══ PDF EXPORT ═════════════════════════════════════════════════════════════
        if st.button("📄 Generate PDF Report"):
            with st.spinner("Building PDF..."):
                try:
                    from src.report_generator import export_pdf
                    pdf_path = export_pdf(
                        metrics, analysis, "output/perfai_report.pdf",
                        test_name=test_name,
                        created_by="PerfAI User",
                    )
                    with open(pdf_path, "rb") as f:
                        st.session_state["pdf_bytes"] = f.read()
                except Exception as e:
                    st.session_state.pop("pdf_bytes", None)
                    st.error(f"PDF generation failed: {e}")

        if st.session_state.get("pdf_bytes"):
            st.download_button(
                "⬇ Download PDF Report",
                data=st.session_state["pdf_bytes"],
                file_name="perfai_performance_report.pdf",
                mime="application/pdf",
                key="dl_pdf",
            )

        st.download_button(
            "⬇ Download raw metrics (JSON)",
            data=json.dumps({"metrics": metrics, "analysis": analysis}, indent=2, default=str),
            file_name="perfai_metrics.json",
            mime="application/json",
        )


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 4 — Compare Results
# ═══════════════════════════════════════════════════════════════════════════════
with tab4:
    import plotly.graph_objects as go
    from src.results_parser import parse_results as _parse_results

    st.markdown("""
    <div style="background:linear-gradient(135deg,#FFFFFF,#F5F3FF);
                border:1.5px solid #DDD6FE;border-radius:16px;
                padding:22px 26px;margin-bottom:20px;
                box-shadow:0 2px 14px rgba(124,58,237,0.09);">
        <div style="font-size:1.5rem;font-weight:800;color:#1E1B4B;margin-bottom:6px;">⚖ Compare Test Results</div>
        <div style="font-size:0.9rem;color:#5B21B6;">
            Upload 2 or more <code>.jtl</code> files to compare performance across runs side-by-side.
        </div>
    </div>
    <div style="height:3px;background:linear-gradient(90deg,#7C3AED,#A78BFA);border-radius:4px;margin-bottom:22px;"></div>
    """, unsafe_allow_html=True)

    uploaded_files = st.file_uploader(
        "Upload JTL files (select 2 or more)",
        type=["jtl", "csv"],
        accept_multiple_files=True,
        key="compare_upload",
    )

    if uploaded_files and len(uploaded_files) >= 2:
        st.markdown(f'<div style="font-size:0.85rem;color:#6B7280;margin-bottom:10px;">{len(uploaded_files)} files selected. Give each run a label:</div>', unsafe_allow_html=True)
        cols = st.columns(min(len(uploaded_files), 4))
        test_labels = []
        for i, f in enumerate(uploaded_files):
            default_label = f"Run {i+1}: {f.name[:18]}"
            lbl = cols[i % 4].text_input(f"Label {i+1}", value=default_label, key=f"lbl_{i}")
            test_labels.append(lbl)

        if st.button("⚖ Compare Now", type="primary"):
            all_metrics = {}
            errors_found = []
            for f, lbl in zip(uploaded_files, test_labels):
                try:
                    os.makedirs("output", exist_ok=True)
                    tmp_path = f"output/_cmp_{f.name}"
                    with open(tmp_path, "wb") as fp:
                        fp.write(f.read())
                    all_metrics[lbl] = _parse_results(tmp_path)
                    os.remove(tmp_path)
                except Exception as e:
                    errors_found.append(f"{lbl}: {e}")

            if errors_found:
                for err in errors_found:
                    st.error(err)
            if len(all_metrics) >= 2:
                st.session_state["compare_metrics"] = all_metrics
                st.success(f"✅ Parsed {len(all_metrics)} test runs. Scroll down to see comparison.")

    elif uploaded_files and len(uploaded_files) == 1:
        st.warning("Please upload at least 2 JTL files to compare.")
    elif not uploaded_files and not st.session_state.get("compare_metrics"):
        st.markdown("""
        <div style="background:#F5F3FF;border:1.5px solid #DDD6FE;border-radius:12px;
                    padding:28px 32px;text-align:center;margin-top:10px;">
            <div style="font-size:2rem;margin-bottom:10px;">📂</div>
            <div style="font-size:1rem;font-weight:700;color:#4C1D95;margin-bottom:6px;">
                No files uploaded yet
            </div>
            <div style="font-size:0.88rem;color:#6D28D9;">
                Upload 2 or more <code>.jtl</code> files above to compare test runs side-by-side.
            </div>
        </div>
        """, unsafe_allow_html=True)

    # ── Show comparison if data is ready ─────────────────────────────────────
    cmp = st.session_state.get("compare_metrics", {})
    if len(cmp) >= 2:
        labels = list(cmp.keys())
        _pcfg  = {"scrollZoom": False, "displayModeBar": False, "displaylogo": False}
        _PBASE = dict(
            plot_bgcolor="white", paper_bgcolor="white",
            font=dict(family="Inter, sans-serif", size=12, color="#374151"),
            margin=dict(l=50, r=30, t=55, b=50),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                        bgcolor="rgba(255,255,255,0.95)", bordercolor="#E5E7EB", borderwidth=1),
            xaxis=dict(showgrid=True, gridcolor="#F3F4F6", zeroline=False),
            yaxis=dict(showgrid=True, gridcolor="#F3F4F6", zeroline=False),
            hovermode="x unified",
        )
        COLORS = ["#7C3AED","#059669","#DC2626","#CA8A04","#2563EB","#DB2777"]

        st.markdown('<hr style="border:none;border-top:3px solid #7C3AED;margin:8px 0 20px 0;">', unsafe_allow_html=True)

        # ── SUMMARY COMPARISON TABLE ──────────────────────────────────────────
        st.markdown('<div style="font-size:1.2rem;font-weight:800;color:#111827;margin-bottom:10px;">Summary Comparison</div>', unsafe_allow_html=True)

        metric_rows = []
        metric_keys = [
            ("Total Requests",  lambda s: s["total_requests"]),
            ("Duration (s)",    lambda s: s["duration_seconds"]),
            ("Throughput (r/s)",lambda s: s["throughput_rps"]),
            ("Error Rate (%)",  lambda s: s["error_rate_pct"]),
            ("Avg RT (ms)",     lambda s: s["avg_ms"]),
            ("P50 (ms)",        lambda s: s["p50_ms"]),
            ("P90 (ms)",        lambda s: s["p90_ms"]),
            ("P95 (ms)",        lambda s: s["p95_ms"]),
            ("P99 (ms)",        lambda s: s["p99_ms"]),
            ("Max RT (ms)",     lambda s: s["max_ms"]),
        ]
        for metric_name, extractor in metric_keys:
            row = {"Metric": metric_name}
            vals = []
            for lbl in labels:
                try:
                    v = extractor(cmp[lbl]["summary"])
                    vals.append(v)
                    row[lbl] = v
                except Exception:
                    row[lbl] = "—"
                    vals.append(None)
            metric_rows.append(row)

        cmp_df = pd.DataFrame(metric_rows).set_index("Metric")

        # Colour the best/worst for each numeric metric
        def _highlight_cmp(df):
            styles = pd.DataFrame("", index=df.index, columns=df.columns)
            good_low = {"Error Rate (%)","Avg RT (ms)","P50 (ms)","P90 (ms)","P95 (ms)","P99 (ms)","Max RT (ms)"}
            for metric in df.index:
                vals = pd.to_numeric(df.loc[metric], errors="coerce").dropna()
                if vals.empty:
                    continue
                best_col = vals.idxmin() if metric in good_low else vals.idxmax()
                worst_col = vals.idxmax() if metric in good_low else vals.idxmin()
                styles.loc[metric, best_col]  = "background-color:#ECFDF5;color:#065F46;font-weight:700;"
                styles.loc[metric, worst_col] = "background-color:#FEF2F2;color:#991B1B;font-weight:700;"
            return styles

        st.dataframe(cmp_df.style.apply(_highlight_cmp, axis=None), use_container_width=True)

        st.markdown("""
        <div style="font-size:0.78rem;color:#9CA3AF;margin:4px 0 18px 0;">
            🟢 Green = best value &nbsp;|&nbsp; 🔴 Red = worst value &nbsp;|&nbsp; for RT metrics lower is better, for throughput higher is better
        </div>""", unsafe_allow_html=True)

        # ── GROUPED BAR CHARTS ────────────────────────────────────────────────
        _cmp_sec = lambda title: f'''
        <div style="display:flex;align-items:center;gap:10px;margin:28px 0 6px 0;">
            <div style="width:4px;height:28px;background:#7C3AED;border-radius:2px;"></div>
            <span style="font-size:1.2rem;font-weight:800;color:#111827;">{title}</span>
        </div>
        <div style="height:2px;background:linear-gradient(90deg,#7C3AED 60%,transparent);margin-bottom:14px;border-radius:2px;"></div>
        '''
        _zoom_h = '<div style="height:4px;"></div>'

        # Chart 1: Latency percentiles per run
        st.markdown(_cmp_sec("Latency Percentiles"), unsafe_allow_html=True)
        fig_lat = go.Figure()
        percentile_keys = [("Avg", "avg_ms"), ("P50","p50_ms"), ("P90","p90_ms"), ("P95","p95_ms"), ("P99","p99_ms")]
        x_labels = [p[0] for p in percentile_keys]
        for i, lbl in enumerate(labels):
            y_vals = [cmp[lbl]["summary"].get(k, 0) for _, k in percentile_keys]
            fig_lat.add_trace(go.Bar(name=lbl, x=x_labels, y=y_vals,
                                     marker_color=COLORS[i % len(COLORS)], opacity=0.85,
                                     hovertemplate=f"<b>{lbl}</b><br>%{{x}}: %{{y}} ms<extra></extra>"))
        layout_lat = dict(**_PBASE, barmode="group", height=400)
        layout_lat["title"] = dict(text="Latency Percentiles by Run", font=dict(size=14, color="#111827"), x=0)
        layout_lat["yaxis"] = dict(title="Response Time (ms)", showgrid=True, gridcolor="#F3F4F6", zeroline=False)
        fig_lat.update_layout(**layout_lat)
        st.plotly_chart(fig_lat, use_container_width=True, config=_pcfg)
        st.markdown(_zoom_h, unsafe_allow_html=True)

        # Chart 2: Throughput + Error rate
        st.markdown(_cmp_sec("Throughput vs Error Rate"), unsafe_allow_html=True)
        fig_te = go.Figure()
        thr_vals = [cmp[lbl]["summary"].get("throughput_rps", 0) for lbl in labels]
        err_vals = [cmp[lbl]["summary"].get("error_rate_pct", 0) for lbl in labels]
        fig_te.add_trace(go.Bar(name="Throughput (req/s)", x=labels, y=thr_vals,
                                 marker_color="#7C3AED", opacity=0.85, yaxis="y1",
                                 hovertemplate="<b>%{x}</b><br>Throughput: %{y:.2f} req/s<extra></extra>"))
        fig_te.add_trace(go.Scatter(name="Error Rate (%)", x=labels, y=err_vals,
                                     line=dict(color="#DC2626", width=2.5),
                                     mode="lines+markers", marker=dict(size=9), yaxis="y2",
                                     hovertemplate="<b>%{x}</b><br>Error Rate: %{y:.2f}%<extra></extra>"))
        layout_te = dict(**_PBASE, height=400)
        layout_te["title"]  = dict(text="Throughput vs Error Rate", font=dict(size=14, color="#111827"), x=0)
        layout_te["yaxis"]  = dict(title="Throughput (req/s)", showgrid=True, gridcolor="#F3F4F6", zeroline=False)
        layout_te["yaxis2"] = dict(title="Error Rate (%)", overlaying="y", side="right",
                                    showgrid=False, zeroline=False)
        fig_te.update_layout(**layout_te)
        st.plotly_chart(fig_te, use_container_width=True, config=_pcfg)
        st.markdown(_zoom_h, unsafe_allow_html=True)

        # Chart 3: Endpoint-level comparison (P95) — for shared endpoints
        all_eps = set()
        for lbl in labels:
            all_eps.update(cmp[lbl]["endpoints"].keys())
        shared_eps = [ep for ep in all_eps
                      if all(ep in cmp[lbl]["endpoints"] for lbl in labels)]

        if shared_eps:
            st.markdown(_cmp_sec("Per-Endpoint P95 Latency"), unsafe_allow_html=True)
            fig_ep = go.Figure()
            for i, lbl in enumerate(labels):
                y_vals = [cmp[lbl]["endpoints"][ep]["p95_ms"] for ep in shared_eps]
                fig_ep.add_trace(go.Bar(name=lbl, x=shared_eps, y=y_vals,
                                         marker_color=COLORS[i % len(COLORS)], opacity=0.85,
                                         hovertemplate=f"<b>{lbl}</b><br>%{{x}}<br>P95: %{{y}} ms<extra></extra>"))
            layout_ep = dict(**_PBASE, barmode="group", height=420)
            layout_ep["title"] = dict(text="P95 Latency per Endpoint (Shared Endpoints)", font=dict(size=14, color="#111827"), x=0)
            layout_ep["yaxis"] = dict(title="P95 (ms)", showgrid=True, gridcolor="#F3F4F6", zeroline=False)
            layout_ep["xaxis"] = dict(tickangle=-25, showgrid=False, zeroline=False)
            fig_ep.update_layout(**layout_ep)
            st.plotly_chart(fig_ep, use_container_width=True, config=_pcfg)
            st.markdown(_zoom_h, unsafe_allow_html=True)

        # Chart 4: Timeline overlay (avg RT per run)
        has_timeline = all(cmp[lbl].get("timeline") for lbl in labels)
        if has_timeline:
            st.markdown(_cmp_sec("Avg Response Time Over Time"), unsafe_allow_html=True)
            fig_tl = go.Figure()
            for i, lbl in enumerate(labels):
                tl    = cmp[lbl]["timeline"]
                times = [t.get("time","")[-8:-3] or str(j) for j, t in enumerate(tl)]
                avg_rt = [t["avg_ms"] for t in tl]
                fig_tl.add_trace(go.Scatter(x=times, y=avg_rt, name=lbl,
                                             line=dict(color=COLORS[i % len(COLORS)], width=2.5),
                                             mode="lines+markers", marker=dict(size=5),
                                             hovertemplate=f"<b>{lbl}</b><br>Avg RT: %{{y:.1f}} ms<extra></extra>"))
            layout_tl = dict(**_PBASE, height=400)
            layout_tl["title"] = dict(text="Avg Response Time Over Time (All Runs)",
                                       font=dict(size=14, color="#111827"), x=0)
            layout_tl["yaxis"] = dict(title="Avg RT (ms)", showgrid=True, gridcolor="#F3F4F6", zeroline=False)
            layout_tl["xaxis"] = dict(title="Time", showgrid=False, zeroline=False)
            fig_tl.update_layout(**layout_tl)
            st.plotly_chart(fig_tl, use_container_width=True, config=_pcfg)
            st.markdown(_zoom_h, unsafe_allow_html=True)

        # ── EXPORT COMPARISON REPORT ──────────────────────────────────────────
        st.markdown('<hr style="border:none;border-top:3px solid #7C3AED;margin:20px 0;">', unsafe_allow_html=True)
        st.download_button(
            "⬇ Download comparison data (JSON)",
            data=json.dumps({lbl: m["summary"] for lbl, m in cmp.items()}, indent=2, default=str),
            file_name="perfai_comparison.json",
            mime="application/json",
        )
