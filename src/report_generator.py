"""
report_generator.py
BlazeMeter-style PDF performance report + Streamlit chart builders.
Public functions:
    build_charts(metrics)                         -> dict of matplotlib figures
    export_pdf(metrics, analysis, output_path)    -> str (path to PDF)
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    Image, HRFlowable, PageBreak, KeepTogether
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
import io
import os
from datetime import datetime

# ── Colour palette (BlazeMeter-inspired) ──────────────────────────────────────
PURPLE        = "#7C3AED"
PURPLE_LIGHT  = "#EDE9FE"
PURPLE_MID    = "#A78BFA"
GREEN         = "#059669"
RED           = "#DC2626"
AMBER         = "#D97706"
BLUE          = "#2563EB"
DARK          = "#111827"
GRAY          = "#6B7280"
LIGHT_GRAY    = "#9CA3AF"
BORDER        = "#E5E7EB"
BG_LIGHT      = "#F9FAFB"
WHITE         = "#FFFFFF"
INFO_BG       = "#EFF6FF"

# Chart line colours (matching BlazeMeter chart)
C_USERS       = "#7C3AED"   # purple  — active users
C_HIT_TOTAL   = "#16A34A"   # green   — total hits/s
C_RT          = "#CA8A04"   # gold    — avg response time
C_ERRORS      = "#DC2626"   # red     — error hits/s

# ReportLab colour objects
PDF_PURPLE       = colors.HexColor(PURPLE)
PDF_PURPLE_LIGHT = colors.HexColor(PURPLE_LIGHT)
PDF_GREEN        = colors.HexColor(GREEN)
PDF_RED          = colors.HexColor(RED)
PDF_AMBER        = colors.HexColor(AMBER)
PDF_BLUE         = colors.HexColor(BLUE)
PDF_DARK         = colors.HexColor(DARK)
PDF_GRAY         = colors.HexColor(GRAY)
PDF_LIGHT_GRAY   = colors.HexColor(LIGHT_GRAY)
PDF_BORDER       = colors.HexColor(BORDER)
PDF_BG_LIGHT     = colors.HexColor(BG_LIGHT)
PDF_INFO_BG      = colors.HexColor(INFO_BG)
PDF_WHITE        = colors.white


# ── Public API ─────────────────────────────────────────────────────────────────

def build_charts(metrics: dict) -> dict:
    """Build matplotlib charts (used for PDF export only)."""
    return {
        "timeline":       _timeline_chart(metrics),
        "latency_bar":    _latency_bar_chart(metrics),
        "error_rate_bar": _error_rate_bar_chart(metrics),
        "latency_spread": _latency_spread_chart(metrics),
        "error_pie":      _error_pie_chart(metrics),
    }


def build_interactive_charts(metrics: dict) -> dict:
    """Build interactive Plotly charts for the Streamlit dashboard (zoom/pan/hover)."""
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    return {
        "timeline":       _timeline_plotly(metrics, go, make_subplots),
        "latency_bar":    _latency_bar_plotly(metrics, go),
        "error_rate_bar": _error_rate_bar_plotly(metrics, go),
        "latency_spread": _latency_spread_plotly(metrics, go),
        "error_pie":      _error_pie_plotly(metrics, go),
    }


# ── Interactive Plotly chart builders ─────────────────────────────────────────

_PLOTLY_LAYOUT = dict(
    plot_bgcolor="white",
    paper_bgcolor="white",
    font=dict(family="Inter, sans-serif", size=12, color="#374151"),
    margin=dict(l=50, r=60, t=60, b=50),
    legend=dict(
        orientation="h",
        yanchor="bottom", y=1.02,
        xanchor="left",   x=0,
        bgcolor="rgba(255,255,255,0.95)",
        bordercolor="#E5E7EB", borderwidth=1,
        font=dict(size=11),
    ),
    xaxis=dict(showgrid=True, gridcolor="#F3F4F6", zeroline=False,
               linecolor="#E5E7EB", tickfont=dict(size=10)),
    yaxis=dict(showgrid=True, gridcolor="#F3F4F6", zeroline=False,
               linecolor="#E5E7EB", tickfont=dict(size=10)),
    hovermode="x unified",
    modebar_remove=["lasso2d", "select2d"],
)


def _timeline_plotly(metrics, go, make_subplots):
    timeline = metrics.get("timeline", [])
    if not timeline:
        fig = go.Figure()
        fig.add_annotation(text="No timeline data available",
                           xref="paper", yref="paper", x=0.5, y=0.5,
                           showarrow=False, font=dict(size=14, color="#9CA3AF"))
        fig.update_layout(**_PLOTLY_LAYOUT, height=350)
        return fig

    times      = [t.get("time", "")[-8:-3] or str(i) for i, t in enumerate(timeline)]
    users      = [t.get("active_users", 0) for t in timeline]
    hits_total = [t["throughput"]           for t in timeline]
    avg_rt     = [t["avg_ms"]               for t in timeline]
    err_rate   = [t.get("error_rate", 0)    for t in timeline]

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # Users — purple fill
    fig.add_trace(go.Scatter(
        x=times, y=users, name="ALL - Users",
        line=dict(color="#7C3AED", width=2.5),
        fill="tozeroy", fillcolor="rgba(124,58,237,0.07)",
        mode="lines+markers", marker=dict(size=6, color="#7C3AED"),
        hovertemplate="<b>Users:</b> %{y}<extra></extra>",
    ), secondary_y=False)

    # Hit/s Total — green
    fig.add_trace(go.Scatter(
        x=times, y=hits_total, name="ALL - Hit/s Total",
        line=dict(color="#16A34A", width=2),
        mode="lines+markers", marker=dict(size=5, color="#16A34A"),
        hovertemplate="<b>Hits/s Total:</b> %{y:.2f}<extra></extra>",
    ), secondary_y=True)

    # Avg Response Time — gold dashed
    fig.add_trace(go.Scatter(
        x=times, y=avg_rt, name="ALL - Avg - Response Time",
        line=dict(color="#CA8A04", width=2, dash="dash"),
        mode="lines+markers", marker=dict(size=5, color="#CA8A04"),
        hovertemplate="<b>Avg RT:</b> %{y:.1f} ms<extra></extra>",
    ), secondary_y=True)

    # Errors — red
    fig.add_trace(go.Scatter(
        x=times, y=err_rate, name="ALL - Hit/s Errors",
        line=dict(color="#DC2626", width=2),
        mode="lines+markers", marker=dict(size=5, color="#DC2626"),
        hovertemplate="<b>Error Rate:</b> %{y:.2f}%<extra></extra>",
    ), secondary_y=True)

    layout = dict(**_PLOTLY_LAYOUT)
    layout["height"] = 420
    layout["yaxis"]  = dict(title="Users", showgrid=True, gridcolor="#F3F4F6",
                             zeroline=False, linecolor="#E5E7EB", tickfont=dict(size=10))
    layout["yaxis2"] = dict(title="Hits/s  /  RT (ms)  /  Errors", showgrid=False,
                             zeroline=False, linecolor="#E5E7EB", tickfont=dict(size=10))
    fig.update_layout(**layout)
    return fig


def _latency_bar_plotly(metrics, go):
    endpoints = metrics.get("endpoints", {})
    labels = list(endpoints.keys())
    p50 = [ep["p50_ms"] for ep in endpoints.values()]
    p95 = [ep["p95_ms"] for ep in endpoints.values()]
    p99 = [ep["p99_ms"] for ep in endpoints.values()]

    fig = go.Figure(data=[
        go.Bar(name="P50", x=labels, y=p50, marker_color="#7C3AED", opacity=0.85,
               hovertemplate="<b>%{x}</b><br>P50: %{y} ms<extra></extra>"),
        go.Bar(name="P95", x=labels, y=p95, marker_color="#CA8A04", opacity=0.85,
               hovertemplate="<b>%{x}</b><br>P95: %{y} ms<extra></extra>"),
        go.Bar(name="P99", x=labels, y=p99, marker_color="#DC2626", opacity=0.85,
               hovertemplate="<b>%{x}</b><br>P99: %{y} ms<extra></extra>"),
    ])
    layout = dict(**_PLOTLY_LAYOUT)
    layout["barmode"] = "group"
    layout["height"]  = 380
    layout["title"]   = dict(text="Latency by Endpoint (P50 / P95 / P99)",
                              font=dict(size=13, color="#111827"), x=0)
    layout["yaxis"]   = dict(title="Response Time (ms)", showgrid=True,
                              gridcolor="#F3F4F6", zeroline=False)
    layout["xaxis"]   = dict(tickangle=-25, tickfont=dict(size=10),
                              showgrid=False, zeroline=False)
    fig.update_layout(**layout)
    return fig


def _error_rate_bar_plotly(metrics, go):
    endpoints = metrics.get("endpoints", {})
    ordered = sorted(endpoints.items(), key=lambda x: x[1].get("error_rate_pct", 0), reverse=True)
    labels = [l for l, _ in ordered][:10]
    values = [d.get("error_rate_pct", 0) for _, d in ordered][:10]
    bar_colors = ["#DC2626" if v >= 5 else "#D97706" if v >= 1 else "#059669" for v in values]

    fig = go.Figure(go.Bar(
        x=values[::-1], y=labels[::-1], orientation="h",
        marker_color=bar_colors[::-1], opacity=0.85,
        hovertemplate="<b>%{y}</b><br>Error Rate: %{x:.2f}%<extra></extra>",
    ))
    layout = dict(**_PLOTLY_LAYOUT)
    layout["height"] = 380
    layout["title"]  = dict(text="Endpoint Error Rates", font=dict(size=13, color="#111827"), x=0)
    layout["xaxis"]  = dict(title="Error Rate (%)", showgrid=True, gridcolor="#F3F4F6", zeroline=False)
    layout["yaxis"]  = dict(showgrid=False, zeroline=False, tickfont=dict(size=10))
    layout["legend"] = dict(visible=False)
    fig.update_layout(**layout)
    return fig


def _latency_spread_plotly(metrics, go):
    endpoints = metrics.get("endpoints", {})
    ordered = sorted(endpoints.items(), key=lambda x: x[1].get("p95_ms", 0), reverse=True)
    labels = [l for l, _ in ordered][:8]
    avg = [d.get("avg_ms", 0) for _, d in ordered][:8]
    p95 = [d.get("p95_ms", 0) for _, d in ordered][:8]
    p99 = [d.get("p99_ms", 0) for _, d in ordered][:8]

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=labels, y=p99, name="P99", fill="tonexty",
                              fillcolor="rgba(220,38,38,0.05)",
                              line=dict(color="#DC2626", width=2),
                              mode="lines+markers", marker=dict(size=7),
                              hovertemplate="<b>%{x}</b><br>P99: %{y} ms<extra></extra>"))
    fig.add_trace(go.Scatter(x=labels, y=p95, name="P95", fill="tonexty",
                              fillcolor="rgba(202,138,4,0.06)",
                              line=dict(color="#CA8A04", width=2),
                              mode="lines+markers", marker=dict(size=7),
                              hovertemplate="<b>%{x}</b><br>P95: %{y} ms<extra></extra>"))
    fig.add_trace(go.Scatter(x=labels, y=avg, name="Avg",
                              line=dict(color="#059669", width=2.5),
                              mode="lines+markers", marker=dict(size=8),
                              hovertemplate="<b>%{x}</b><br>Avg: %{y} ms<extra></extra>"))
    layout = dict(**_PLOTLY_LAYOUT)
    layout["height"] = 380
    layout["title"]  = dict(text="Latency Spread Across Endpoints",
                              font=dict(size=13, color="#111827"), x=0)
    layout["yaxis"]  = dict(title="Latency (ms)", showgrid=True, gridcolor="#F3F4F6", zeroline=False)
    layout["xaxis"]  = dict(tickangle=-18, tickfont=dict(size=10), showgrid=False, zeroline=False)
    fig.update_layout(**layout)
    return fig


def _error_pie_plotly(metrics, go):
    errors = metrics.get("errors", {})
    fig = go.Figure()
    if not errors:
        fig.add_annotation(text="No errors recorded", xref="paper", yref="paper",
                           x=0.5, y=0.5, showarrow=False,
                           font=dict(size=14, color="#059669"))
        fig.update_layout(**_PLOTLY_LAYOUT, height=320)
        return fig

    codes  = [f"HTTP {c}" for c in errors.keys()]
    counts = [e["count"] for e in errors.values()]
    colors_list = ["#DC2626", "#D97706", "#2563EB", "#7C3AED", "#059669"]

    fig.add_trace(go.Pie(
        labels=codes, values=counts,
        marker=dict(colors=colors_list[:len(codes)], line=dict(color="white", width=2)),
        textfont=dict(size=11),
        hovertemplate="<b>%{label}</b><br>Count: %{value}<br>Share: %{percent}<extra></extra>",
    ))
    layout = dict(**_PLOTLY_LAYOUT)
    layout["height"] = 340
    layout["title"]  = dict(text="Error Distribution", font=dict(size=13, color="#111827"), x=0)
    layout["legend"] = dict(orientation="v", x=1, y=0.5)
    fig.update_layout(**layout)
    return fig


def export_pdf(metrics: dict, analysis: dict, output_path: str,
               test_name: str = "PerfAI Load Test",
               created_by: str = "PerfAI") -> str:
    """Generate a BlazeMeter-style PDF report. Returns the saved path."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    doc = SimpleDocTemplate(
        output_path, pagesize=A4,
        leftMargin=1.8*cm, rightMargin=1.8*cm,
        topMargin=2.0*cm,  bottomMargin=2.2*cm,
    )

    styles = _build_styles()
    story  = []

    _section_header(story, styles, metrics, analysis, test_name, created_by)
    _section_filters(story, styles, metrics)
    _section_kpi_banner(story, styles, metrics)
    _section_test_setup(story, styles, metrics, test_name, created_by)
    _section_timeline(story, styles, metrics)
    _section_engine_health(story, styles, metrics)
    _section_request_stats(story, styles, metrics)
    _section_errors(story, styles, metrics)
    _section_ai_analysis(story, styles, analysis)
    _section_glossary(story, styles)
    _section_about(story, styles)

    doc.build(story, onFirstPage=_page_chrome, onLaterPages=_page_chrome)
    return output_path


# ══════════════════════════════════════════════════════════════════════════════
# PDF SECTIONS
# ══════════════════════════════════════════════════════════════════════════════

def _section_header(story, styles, metrics, analysis, test_name, created_by):
    s = metrics["summary"]
    duration_min = round(s["duration_seconds"] / 60, 1)

    # Top meta row: brand left, metadata right
    meta = (
        f'<font color="{DARK}"><b>Report Created By:</b> {created_by}</font><br/>'
        f'<font color="{DARK}"><b>Date of Run:</b> {datetime.now().strftime("%a, %m/%d/%Y - %H:%M")}</font><br/>'
        f'<font color="{DARK}"><b>Duration:</b> {duration_min} minutes</font>'
    )
    header_data = [
        [
            Paragraph(f'<font size="16" color="{PURPLE}"><b>⚡ PerfAI</b></font>', styles["body"]),
            Paragraph(meta, ParagraphStyle("meta", fontSize=9, leading=14, alignment=TA_RIGHT)),
        ]
    ]
    ht = Table(header_data, colWidths=[9*cm, 8.4*cm])
    ht.setStyle(TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
        ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(ht)
    story.append(Spacer(1, 0.3*cm))
    story.append(Paragraph("Load Test Report", styles["small_label"]))
    story.append(Paragraph(test_name, styles["cover_title"]))
    story.append(Spacer(1, 0.4*cm))
    story.append(HRFlowable(width="100%", thickness=2, color=PDF_PURPLE, spaceAfter=0.5*cm))


def _section_filters(story, styles, metrics):
    s = metrics["summary"]
    _pdf_section_title(story, "Filters Applied")

    time_range = f"{s.get('test_start','—')}  →  {s.get('test_end','—')}"
    rows = [
        [_label("Time Range:"),       _purple_pill(time_range)],
        [_label("Scenarios:"),        _purple_pill("All")],
        [_label("Time Displayed In:"), _purple_pill("Milliseconds")],
        [_label("Locations:"),        _purple_pill("All")],
    ]
    t = Table(rows, colWidths=[4*cm, 13.4*cm])
    t.setStyle(TableStyle([
        ("FONTSIZE",      (0, 0), (-1, -1), 9),
        ("TOPPADDING",    (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW",     (0, 0), (-1, -2), 0.4, colors.HexColor("#F3F4F6")),
    ]))
    # Wrap in a light box
    outer = Table([[t]], colWidths=[17.4*cm])
    outer.setStyle(TableStyle([
        ("BOX",           (0, 0), (-1, -1), 0.8, PDF_BORDER),
        ("BACKGROUND",    (0, 0), (-1, -1), colors.HexColor("#FAFAFA")),
        ("TOPPADDING",    (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING",   (0, 0), (-1, -1), 10),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
    ]))
    story.append(outer)
    story.append(Spacer(1, 0.5*cm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=PDF_BORDER, spaceAfter=0.4*cm))


def _section_kpi_banner(story, styles, metrics):
    s = metrics["summary"]
    p90_s = round(s["p90_ms"] / 1000, 2)
    bw = s.get("avg_bandwidth_kbps", 0)
    bw_str = f"{bw:.2f} KiB/s" if bw else "N/A"
    max_u = str(s.get("max_users", 0) or "N/A")

    err_color = RED if float(s.get("error_rate_pct", 0) or 0) >= 5 else \
                AMBER if float(s.get("error_rate_pct", 0) or 0) >= 1 else PURPLE

    # Each KPI is a mini 2-row table so value+unit stay on one line and label sits below
    def kpi_cell(value, unit, label, val_color=PURPLE):
        val_unit = Paragraph(
            f'<font size="15" color="{val_color}"><b>{value}</b></font>'
            f'<font size="9" color="{GRAY}"> {unit}</font>',
            ParagraphStyle("kv", leading=18, alignment=TA_LEFT)
        )
        lbl = Paragraph(
            f'<font size="7.5" color="{LIGHT_GRAY}">{label}</font>',
            ParagraphStyle("kl", leading=11, alignment=TA_LEFT)
        )
        cell_t = Table([[val_unit], [lbl]], colWidths=[2.7*cm])
        cell_t.setStyle(TableStyle([
            ("LEFTPADDING",   (0, 0), (-1, -1), 8),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 4),
            ("TOPPADDING",    (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        return cell_t

    kpi_cells = [
        kpi_cell(max_u,                          "VU",     "Max Users"),
        kpi_cell(s["throughput_rps"],            "Hits/s", "Avg. Throughput"),
        kpi_cell(f"{s['error_rate_pct']:.2f}",   "%",      "Errors",            err_color),
        kpi_cell(f"{s['avg_ms']:.0f}",           "ms",     "Avg. Response Time"),
        kpi_cell(f"{p90_s:.2f}",                 "s",      "90% Response Time"),
        kpi_cell(bw_str,                          "",       "Avg. Bandwidth"),
    ]

    kt = Table([kpi_cells], colWidths=[2.9*cm]*6)
    kt.setStyle(TableStyle([
        ("BOX",           (0, 0), (-1, -1), 1,   PDF_BORDER),
        ("INNERGRID",     (0, 0), (-1, -1), 0.5, PDF_BORDER),
        ("BACKGROUND",    (0, 0), (-1, -1), PDF_WHITE),
        ("TOPPADDING",    (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(kt)
    story.append(Spacer(1, 0.5*cm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=PDF_BORDER, spaceAfter=0.4*cm))


def _section_test_setup(story, styles, metrics, test_name, created_by):
    s = metrics["summary"]
    duration_min = round(s["duration_seconds"] / 60, 1)

    _pdf_section_title(story, "Test Setup Details")

    rows = [
        [_label("Executed By:"),    Paragraph(f'<font size="9" color="{DARK}"><b>{created_by}</b></font>',
                                              ParagraphStyle("v", leading=13))],
        [_label("Test Types:"),     _purple_pill("JMeter")],
        [_label("Test Started:"),   Paragraph(f'<font size="9" color="{DARK}">{s.get("test_start", "—")}</font>',
                                              ParagraphStyle("v", leading=13))],
        [_label("Test Ended:"),     Paragraph(f'<font size="9" color="{DARK}">{s.get("test_end", "—")}</font>',
                                              ParagraphStyle("v", leading=13))],
        [_label("Time Elapsed:"),   Paragraph(f'<font size="9" color="{DARK}">{duration_min} minutes</font>',
                                              ParagraphStyle("v", leading=13))],
        [_label("Total Requests:"), Paragraph(f'<font size="9" color="{DARK}"><b>{s["total_requests"]:,}</b></font>',
                                              ParagraphStyle("v", leading=13))],
        [_label("Locations Used:"), _purple_pill("Local")],
    ]
    t = Table(rows, colWidths=[4*cm, 13.4*cm])
    t.setStyle(TableStyle([
        ("FONTSIZE",      (0, 0), (-1, -1), 9),
        ("TOPPADDING",    (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW",     (0, 0), (-1, -2), 0.4, colors.HexColor("#F3F4F6")),
        ("LINEBELOW",     (0, -1), (-1, -1), 0.4, colors.HexColor("#F3F4F6")),
    ]))
    outer = Table([[t]], colWidths=[17.4*cm])
    outer.setStyle(TableStyle([
        ("BOX",           (0, 0), (-1, -1), 0.8, PDF_BORDER),
        ("BACKGROUND",    (0, 0), (-1, -1), PDF_WHITE),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 12),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 12),
    ]))
    story.append(outer)
    story.append(Spacer(1, 0.5*cm))
    story.append(HRFlowable(width="100%", thickness=2, color=PDF_PURPLE, spaceAfter=0.5*cm))


def _section_timeline(story, styles, metrics):
    _pdf_section_title(story, "Timeline")
    story.append(Spacer(1, 0.1*cm))

    # Chart Resolution badge
    cr_row = [["Chart Resolution:", _purple_pill("Dynamic")]]
    cr_t = Table(cr_row, colWidths=[3.5*cm, 14*cm])
    cr_t.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (0, -1), PDF_GRAY),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(cr_t)
    story.append(Spacer(1, 0.3*cm))

    # Chart header bar (matches BlazeMeter's light purple subsection bar)
    sub_data = [[Paragraph('<font size="10" color="#5B21B6"><b>Main Timeline Chart</b></font>',
                           ParagraphStyle("sub", leading=14))]]
    sub_t = Table(sub_data, colWidths=[17.4*cm])
    sub_t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), PDF_PURPLE_LIGHT),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING",   (0, 0), (-1, -1), 10),
    ]))
    # Keep label + chart together so they never split across pages
    fig = _timeline_chart(metrics)
    story.append(KeepTogether([
        sub_t,
        Spacer(1, 0.2*cm),
        _fig_to_image(fig, width=17*cm),
    ]))
    story.append(Spacer(1, 0.5*cm))
    story.append(HRFlowable(width="100%", thickness=2, color=PDF_PURPLE, spaceAfter=0.5*cm))


def _section_engine_health(story, styles, metrics):
    """Engine health charts derived from timeline data (throughput → simulated server metrics)."""
    timeline = metrics.get("timeline", [])
    if not timeline:
        return

    story.append(PageBreak())
    _pdf_section_title(story, "Engine Health")
    story.append(Spacer(1, 0.2*cm))

    # Derive proxy metrics from JTL timeline
    import numpy as np

    n = len(timeline)
    thr   = [t["throughput"]           for t in timeline]
    rt    = [t["avg_ms"]               for t in timeline]
    users = [t.get("active_users", 0)  for t in timeline]
    errs  = [t.get("error_rate", 0)    for t in timeline]
    x     = list(range(n))

    max_thr  = max(thr)  if max(thr)  > 0 else 1
    max_rt   = max(rt)   if max(rt)   > 0 else 1
    max_user = max(users) if max(users) > 0 else 1

    # --- Memory % ---  scales with user count + small noise
    mem_base = [30 + 40 * (u / max_user) for u in users]
    mem = [min(95, v + 3 * np.sin(i * 0.7)) for i, v in enumerate(mem_base)]

    # --- Active Connections --- scales with throughput
    conn = [int(20 + 80 * (t / max_thr) + 5 * np.sin(i * 0.5)) for i, t in enumerate(thr)]

    # --- Network I/O (KB/s) --- proportional to throughput
    bw_kbps = s_val = metrics["summary"].get("avg_bandwidth_kbps", 0) or 0
    net_scale = bw_kbps / max_thr if bw_kbps and max_thr else 50
    net_in  = [max(0, t * net_scale * 0.6 + 5 * np.cos(i * 0.4)) for i, t in enumerate(thr)]
    net_out = [max(0, t * net_scale * 0.3 + 3 * np.sin(i * 0.3)) for i, t in enumerate(thr)]

    # --- CPU % --- correlates with response time spikes
    cpu_base = [20 + 50 * (r / max_rt) for r in rt]
    cpu = [min(98, v + 4 * np.cos(i * 0.6)) for i, v in enumerate(cpu_base)]

    time_labels = [t.get("time", "")[-8:-3] if t.get("time") else str(i)
                   for i, t in enumerate(timeline)]
    tick_step = max(1, n // 5)

    # Single 2×2 grid — all 4 charts on one page
    fig, axes = plt.subplots(2, 2, figsize=(11, 5.5))
    fig.patch.set_facecolor("white")

    panels = [
        (axes[0, 0], "Memory (%)",       [mem],              ["#7C3AED"],          ["Memory"]),
        (axes[0, 1], "Connections",       [conn],             ["#2563EB"],          ["Active Conn."]),
        (axes[1, 0], "Network I/O (KB/s)",[net_in, net_out],  ["#059669","#D97706"],["Net In","Net Out"]),
        (axes[1, 1], "CPU (%)",           [cpu],              ["#DC2626"],          ["CPU"]),
    ]

    for ax, title, series_list, colors_list, labels_list in panels:
        _apply_light_style(fig, ax)
        for data, color, lbl in zip(series_list, colors_list, labels_list):
            ax.plot(x, [float(v) for v in data], color=color, linewidth=1.5, label=lbl)
        ax.set_title(title, fontsize=8, loc="left", pad=4, color=DARK, fontweight="bold")
        ax.set_xticks(x[::tick_step])
        ax.set_xticklabels(time_labels[::tick_step], fontsize=6, rotation=30, ha="right")
        ax.legend(fontsize=6.5, frameon=True, framealpha=0.9, edgecolor=BORDER, loc="best")
        ax.tick_params(labelsize=7)

    plt.tight_layout(pad=0.8)
    fig.subplots_adjust(hspace=0.5, wspace=0.35)
    story.append(_fig_to_image(fig, width=17*cm))

    story.append(Spacer(1, 0.2*cm))
    story.append(Paragraph(
        f'<font size="8" color="{GRAY}">* Memory, Connections, Network I/O and CPU are estimated '
        f'from JTL throughput and latency patterns. For precise server metrics, '
        f'integrate a server-side monitoring agent.</font>',
        ParagraphStyle("note", leading=12, leftIndent=4)
    ))
    story.append(Spacer(1, 0.3*cm))
    story.append(HRFlowable(width="100%", thickness=2, color=PDF_PURPLE, spaceAfter=0.5*cm))


def _section_request_stats(story, styles, metrics):
    _pdf_section_title(story, "Request Stats")
    story.append(Spacer(1, 0.2*cm))

    endpoints = metrics.get("endpoints", {})
    n = len(endpoints)

    # Info box
    info_data = [[
        Paragraph(
            f'<font size="9" color="{BLUE}">ⓘ  Showing {min(n, 25)} of {n} endpoint records.</font>',
            ParagraphStyle("info", leading=12)
        )
    ]]
    info_t = Table(info_data, colWidths=[17.4*cm])
    info_t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), PDF_INFO_BG),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING",   (0, 0), (-1, -1), 10),
        ("BOX",           (0, 0), (-1, -1), 0.5, colors.HexColor("#BFDBFE")),
    ]))
    story.append(info_t)
    story.append(Spacer(1, 0.3*cm))

    # Table header
    s = metrics["summary"]
    all_row = [
        _th("Element Label"),
        _th("# Samples"),
        _th("Avg. Response (ms)"),
        _th("90% line (ms)"),
        _th("95% line (ms)"),
        _th("Error Count"),
        _th("Avg. Hits/s"),
    ]
    rows = [all_row]

    # ALL row
    dur = s["duration_seconds"] or 1
    rows.append([
        Paragraph('<b>ALL</b>', ParagraphStyle("allrow", fontSize=9, leading=12)),
        _td(str(s["total_requests"])),
        _td(f"{s['avg_ms']:.2f}"),
        _td(str(s["p90_ms"])),
        _td(str(s["p95_ms"])),
        _td(str(s["error_count"])),
        _td(f"{s['throughput_rps']:.2f}"),
    ])

    for label, ep in list(endpoints.items())[:24]:
        ep_hits = round(ep["total_requests"] / dur, 2)
        rows.append([
            Paragraph(f'<font size="8" color="{DARK}">{label[:30]}</font>',
                      ParagraphStyle("ep", leading=11)),
            _td(str(ep["total_requests"])),
            _td(f"{ep['avg_ms']:.2f}"),
            _td(str(ep["p90_ms"])),
            _td(str(ep["p95_ms"])),
            _td(str(ep["error_count"])),
            _td(f"{ep_hits:.2f}"),
        ])

    col_w = [5.5*cm, 2*cm, 3*cm, 2.2*cm, 2.2*cm, 2*cm, 2*cm]  # ~18.9 total, fits in 17.4 with padding
    col_w = [5.0*cm, 1.9*cm, 2.8*cm, 2.0*cm, 2.0*cm, 1.9*cm, 1.8*cm]
    t = Table(rows, colWidths=col_w, repeatRows=1)
    t.setStyle(_stats_table_style(len(rows)))
    story.append(t)
    story.append(Spacer(1, 0.5*cm))
    story.append(HRFlowable(width="100%", thickness=2, color=PDF_PURPLE, spaceAfter=0.5*cm))


def _section_errors(story, styles, metrics):
    errors_by_label = metrics.get("errors_by_label", {})
    if not errors_by_label:
        return

    _pdf_section_title(story, "Errors")
    story.append(Spacer(1, 0.1*cm))
    story.append(Paragraph("Grouped by Label", styles["h2_bold"]))
    story.append(Spacer(1, 0.3*cm))

    for label, code_list in errors_by_label.items():
        # Label pill row
        label_row = [["Label:", _purple_pill(label[:50])]]
        lt = Table(label_row, colWidths=[2*cm, 15.4*cm])
        lt.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("TEXTCOLOR", (0, 0), (0, -1), PDF_GRAY),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        story.append(lt)
        story.append(Paragraph("Response Codes", styles["small_label"]))
        story.append(Spacer(1, 0.1*cm))

        err_rows = [[_th("Code"), _th("Description"), _th("Count")]]
        for item in code_list:
            err_rows.append([
                Paragraph(f'<font size="8" color="{DARK}">{item["code"]}</font>',
                          ParagraphStyle("ec", leading=11)),
                Paragraph(f'<font size="8" color="{GRAY}">{item["description"][:80]}</font>',
                          ParagraphStyle("ed", leading=11)),
                _td(str(item["count"])),
            ])
        et = Table(err_rows, colWidths=[4.5*cm, 10*cm, 2.9*cm], repeatRows=1)
        et.setStyle(_stats_table_style(len(err_rows)))
        story.append(et)
        story.append(Spacer(1, 0.4*cm))

    story.append(HRFlowable(width="100%", thickness=2, color=PDF_PURPLE, spaceAfter=0.5*cm))


def _section_ai_analysis(story, styles, analysis):
    verdict = analysis.get("verdict", "warning")
    verdict_color = {"pass": PDF_GREEN, "warning": PDF_AMBER, "fail": PDF_RED}.get(verdict, PDF_AMBER)
    verdict_bg    = {"pass": colors.HexColor("#ECFDF5"), "warning": colors.HexColor("#FFFBEB"),
                     "fail": colors.HexColor("#FEF2F2")}.get(verdict, colors.HexColor("#FFFBEB"))

    _pdf_section_title(story, "AI Analysis & Findings")

    # Verdict banner — matches web UI gradient card style
    verdict_icon = {"pass": "✅", "warning": "⚠️", "fail": "❌"}.get(verdict, "⚠️")
    vd = [[Paragraph(
        f'<font size="13" color="{_hex(verdict_color)}"><b>{verdict_icon}  Verdict: {verdict.upper()}</b></font>'
        f'&nbsp;&nbsp;<font size="10" color="{GRAY}">{analysis.get("headline","")}</font>',
        ParagraphStyle("vd", leading=18)
    )]]
    vt = Table(vd, colWidths=[17.4*cm])
    vt.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), verdict_bg),
        ("TOPPADDING",    (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
        ("LEFTPADDING",   (0, 0), (-1, -1), 16),
        ("BOX",           (0, 0), (-1, -1), 1.2, verdict_color),
        ("ROUNDEDCORNERS",(0, 0), (-1, -1), [6, 6, 6, 6]),
    ]))
    story.append(vt)
    story.append(Spacer(1, 0.4*cm))

    _ftype_cfg = {
        "bottleneck":     {"color": RED,    "bg": "#FEF2F2", "badge_bg": "#FEE2E2", "border": "#FECACA", "label": "BOTTLENECK"},
        "warning":        {"color": AMBER,  "bg": "#FFFBEB", "badge_bg": "#FEF3C7", "border": "#FDE68A", "label": "WARNING"},
        "strength":       {"color": GREEN,  "bg": "#F0FDF4", "badge_bg": "#DCFCE7", "border": "#BBF7D0", "label": "STRENGTH"},
        "recommendation": {"color": PURPLE, "bg": "#F5F3FF", "badge_bg": "#EDE9FE", "border": "#DDD6FE", "label": "RECOMMENDATION"},
    }
    _sev_color = {"HIGH": RED, "MEDIUM": AMBER, "LOW": GREEN}

    findings = sorted(analysis.get("findings", []), key=lambda f: _severity_rank(f.get("severity")))
    for finding in findings:
        ftype = finding.get("type", "recommendation")
        cfg   = _ftype_cfg.get(ftype, _ftype_cfg["recommendation"])
        fc    = colors.HexColor(cfg["color"])
        sev   = (finding.get("severity") or "").upper()
        ep    = (finding.get("endpoint") or "General")[:28]
        sc    = _sev_color.get(sev, GRAY)

        # Thin top colour bar
        top_bar = Table([[""]], colWidths=[17.4*cm])
        top_bar.setStyle(TableStyle([
            ("BACKGROUND",    (0,0),(-1,-1), fc),
            ("TOPPADDING",    (0,0),(-1,-1), 2),
            ("BOTTOMPADDING", (0,0),(-1,-1), 2),
            ("LEFTPADDING",   (0,0),(-1,-1), 0),
            ("RIGHTPADDING",  (0,0),(-1,-1), 0),
        ]))

        # Type badge cell
        badge_t = Table([[
            Paragraph(f'<font size="7" color="{cfg["color"]}"><b>{cfg["label"]}</b></font>',
                      ParagraphStyle("badge", leading=10, alignment=TA_CENTER))
        ]], colWidths=[3.0*cm])
        badge_t.setStyle(TableStyle([
            ("BACKGROUND",    (0,0),(-1,-1), colors.HexColor(cfg["badge_bg"])),
            ("BOX",           (0,0),(-1,-1), 0.6, colors.HexColor(cfg["border"])),
            ("TOPPADDING",    (0,0),(-1,-1), 3),
            ("BOTTOMPADDING", (0,0),(-1,-1), 3),
            ("LEFTPADDING",   (0,0),(-1,-1), 4),
            ("RIGHTPADDING",  (0,0),(-1,-1), 4),
        ]))

        # Severity chip
        sev_t = Table([[
            Paragraph(f'<font size="7" color="{sc}"><b>{sev}</b></font>',
                      ParagraphStyle("sc", leading=10, alignment=TA_CENTER))
        ]], colWidths=[1.5*cm])
        sev_t.setStyle(TableStyle([
            ("BACKGROUND",    (0,0),(-1,-1), colors.white),
            ("BOX",           (0,0),(-1,-1), 0.6, colors.HexColor(sc)),
            ("TOPPADDING",    (0,0),(-1,-1), 3),
            ("BOTTOMPADDING", (0,0),(-1,-1), 3),
            ("LEFTPADDING",   (0,0),(-1,-1), 3),
            ("RIGHTPADDING",  (0,0),(-1,-1), 3),
        ]))

        # Endpoint chip
        ep_t = Table([[
            Paragraph(f'<font size="7" color="{PURPLE}">{ep}</font>',
                      ParagraphStyle("ec", leading=10))
        ]], colWidths=[3.0*cm])
        ep_t.setStyle(TableStyle([
            ("BACKGROUND",    (0,0),(-1,-1), colors.HexColor("#EDE9FE")),
            ("BOX",           (0,0),(-1,-1), 0.6, colors.HexColor("#DDD6FE")),
            ("TOPPADDING",    (0,0),(-1,-1), 3),
            ("BOTTOMPADDING", (0,0),(-1,-1), 3),
            ("LEFTPADDING",   (0,0),(-1,-1), 4),
            ("RIGHTPADDING",  (0,0),(-1,-1), 4),
        ]))

        # Header row: badge | title | sev | ep
        hdr = Table([[
            badge_t,
            Paragraph(f'<font size="10" color="{DARK}"><b>{finding.get("title","")}</b></font>',
                      ParagraphStyle("ft", leading=14)),
            sev_t,
            ep_t,
        ]], colWidths=[3.2*cm, 9.0*cm, 1.8*cm, 3.4*cm])
        hdr.setStyle(TableStyle([
            ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
            ("LEFTPADDING",   (0,0),(-1,-1), 0),
            ("RIGHTPADDING",  (0,0),(-1,-1), 0),
            ("TOPPADDING",    (0,0),(-1,-1), 0),
            ("BOTTOMPADDING", (0,0),(-1,-1), 6),
        ]))

        # Content area
        content = Table([
            [hdr],
            [Paragraph(f'<font size="9" color="{DARK}">{finding.get("description","")}</font>',
                       ParagraphStyle("fd", leading=14))],
        ], colWidths=[17.0*cm])
        content.setStyle(TableStyle([
            ("BACKGROUND",    (0,0),(-1,-1), colors.HexColor(cfg["bg"])),
            ("TOPPADDING",    (0,0),(-1,-1), 10),
            ("BOTTOMPADDING", (0,0),(-1,-1), 10),
            ("LEFTPADDING",   (0,0),(-1,-1), 12),
            ("RIGHTPADDING",  (0,0),(-1,-1), 10),
        ]))

        # Card wrapper: top bar + content + border
        card = Table([[top_bar], [content]], colWidths=[17.4*cm])
        card.setStyle(TableStyle([
            ("BOX",           (0,0),(-1,-1), 0.8, colors.HexColor(cfg["border"])),
            ("TOPPADDING",    (0,0),(-1,-1), 0),
            ("BOTTOMPADDING", (0,0),(-1,-1), 0),
            ("LEFTPADDING",   (0,0),(-1,-1), 0),
            ("RIGHTPADDING",  (0,0),(-1,-1), 0),
        ]))
        story.append(KeepTogether([card, Spacer(1, 0.18*cm)]))

    next_steps = analysis.get("next_steps", [])
    if next_steps:
        story.append(Spacer(1, 0.3*cm))
        story.append(Paragraph("Recommended Next Steps", styles["h2_bold"]))
        for i, step in enumerate(next_steps, 1):
            story.append(Paragraph(f'<font size="9" color="{DARK}"><b>{i}.</b> {step}</font>',
                                   ParagraphStyle("step", leading=14, spaceAfter=4)))

    story.append(Spacer(1, 0.4*cm))
    story.append(HRFlowable(width="100%", thickness=2, color=PDF_PURPLE, spaceAfter=0.5*cm))


def _section_glossary(story, styles):
    _pdf_section_title(story, "Glossary")
    story.append(Spacer(1, 0.2*cm))
    terms = [
        ("Throughput",     "Number of requests completed in a time interval."),
        ("Response Time",  "The time that passed to perform the request and receive full response."),
        ("Latency",        "The time from sending the request, processing it on the server side, "
                           "to the time the client received the first byte."),
        ("Error Rate",     "Percentage of requests that returned a non-2xx response code."),
        ("P90 / P95 / P99","The 90th / 95th / 99th percentile response time. "
                           "E.g. P95 = 95% of requests completed within this time."),
    ]
    rows = [[
        Paragraph(f'<b>{term}</b>', ParagraphStyle("gt", fontSize=9, leading=13)),
        Paragraph(defn, ParagraphStyle("gd", fontSize=9, leading=13, textColor=colors.HexColor(GRAY))),
    ] for term, defn in terms]

    gt = Table(rows, colWidths=[3.5*cm, 13.9*cm])
    gt.setStyle(TableStyle([
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(gt)
    story.append(Spacer(1, 0.4*cm))
    story.append(HRFlowable(width="100%", thickness=2, color=PDF_PURPLE, spaceAfter=0.5*cm))


def _section_about(story, styles):
    about_data = [[Paragraph(
        '<font size="14" color="#7C3AED"><b>⚡ About PerfAI</b></font><br/><br/>'
        '<font size="9" color="#374151">'
        'PerfAI is an AI-powered performance testing platform. It reads your API spec, '
        'generates a JMeter load test, runs it locally or on AWS EC2, and analyses the '
        'results using Azure OpenAI to detect bottlenecks and recommend fixes.<br/><br/>'
        'For more information, visit: <font color="#2563EB">https://github.com/yourusername/perfai</font>'
        '</font>',
        ParagraphStyle("about", leading=16)
    )]]
    at = Table(about_data, colWidths=[17.4*cm])
    at.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), colors.HexColor("#FAFAFA")),
        ("BOX",           (0, 0), (-1, -1), 0.5, PDF_BORDER),
        ("TOPPADDING",    (0, 0), (-1, -1), 16),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 16),
        ("LEFTPADDING",   (0, 0), (-1, -1), 16),
    ]))
    story.append(at)


# ══════════════════════════════════════════════════════════════════════════════
# CHART BUILDERS  (light theme — matches BlazeMeter)
# ══════════════════════════════════════════════════════════════════════════════

def _apply_light_style(fig, axes):
    fig.patch.set_facecolor("white")
    for ax in (axes if hasattr(axes, "__iter__") else [axes]):
        ax.set_facecolor("white")
        ax.tick_params(colors="#374151", labelsize=8)
        ax.xaxis.label.set_color("#374151")
        ax.yaxis.label.set_color("#374151")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_color("#E5E7EB")
        ax.spines["bottom"].set_color("#E5E7EB")
        ax.grid(color="#F3F4F6", linewidth=0.8, alpha=1)


def _timeline_chart(metrics: dict) -> plt.Figure:
    """Multi-line timeline chart: Errors, Avg RT, Active Users, Total Hits — BlazeMeter style."""
    timeline = metrics.get("timeline", [])
    if not timeline:
        fig, ax = plt.subplots(figsize=(11, 3.5))
        _apply_light_style(fig, ax)
        ax.text(0.5, 0.5, "No timeline data", ha="center", va="center",
                color="#9CA3AF", fontsize=11, transform=ax.transAxes)
        ax.axis("off")
        return fig

    times       = list(range(len(timeline)))
    users       = [t.get("active_users", 0) for t in timeline]
    hits_total  = [t["throughput"]           for t in timeline]
    avg_rt      = [t["avg_ms"]               for t in timeline]
    errors      = [t.get("error_rate", 0)    for t in timeline]

    fig, ax1 = plt.subplots(figsize=(11, 4))
    _apply_light_style(fig, ax1)

    # Users — purple fill (prominent, top of legend)
    ax1.fill_between(times, users, alpha=0.08, color=C_USERS)
    ax1.plot(times, users, color=C_USERS, linewidth=1.8, label="ALL - Users", zorder=3,
             marker="o", markersize=4)
    ax1.set_ylabel("Users", fontsize=9, color="#374151")
    ax1.set_ylim(bottom=0)

    # Right axis — Hits/s, RT, Errors (scaled onto user axis for visual clarity)
    ax2 = ax1.twinx()
    ax2.set_facecolor("white")
    ax2.plot(times, hits_total, color=C_HIT_TOTAL, linewidth=1.8, label="ALL - Hit/s Total",
             zorder=3, marker="o", markersize=4)
    ax2.plot(times, avg_rt,     color=C_RT,        linewidth=1.8, label="ALL - Avg - Response Time",
             zorder=3, marker="o", markersize=4, linestyle="--")
    ax2.plot(times, errors,     color=C_ERRORS,    linewidth=1.8, label="ALL - Hit/s Errors",
             zorder=3, marker="o", markersize=4)
    ax2.set_ylabel("Hits/s  /  RT (ms)  /  Errors", fontsize=9, color="#374151")
    ax2.spines["top"].set_visible(False)
    ax2.spines["right"].set_color("#E5E7EB")
    ax2.spines["left"].set_color("#E5E7EB")
    ax2.spines["bottom"].set_color("#E5E7EB")
    ax2.tick_params(colors="#374151", labelsize=8)
    ax2.set_ylim(bottom=0)

    # Time labels
    time_labels = [t.get("time", "")[-8:-3] if t.get("time") else str(i)
                   for i, t in enumerate(timeline)]
    ax1.set_xticks(times[::max(1, len(times)//8)])
    ax1.set_xticklabels(time_labels[::max(1, len(times)//8)], fontsize=7.5)

    lines1, lbl1 = ax1.get_legend_handles_labels()
    lines2, lbl2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, lbl1 + lbl2, fontsize=8, loc="upper left",
               frameon=True, framealpha=0.9, edgecolor="#E5E7EB")

    plt.tight_layout(pad=1.2)
    return fig


def _latency_bar_chart(metrics: dict) -> plt.Figure:
    endpoints = metrics["endpoints"]
    labels = list(endpoints.keys())
    p50 = [ep["p50_ms"] for ep in endpoints.values()]
    p95 = [ep["p95_ms"] for ep in endpoints.values()]
    p99 = [ep["p99_ms"] for ep in endpoints.values()]

    x = range(len(labels))
    width = 0.26
    fig, ax = plt.subplots(figsize=(9, 4))
    _apply_light_style(fig, ax)

    ax.bar([i - width for i in x], p50, width, label="P50", color="#7C3AED", alpha=0.85, zorder=3)
    ax.bar([i         for i in x], p95, width, label="P95", color="#CA8A04", alpha=0.85, zorder=3)
    ax.bar([i + width for i in x], p99, width, label="P99", color="#DC2626", alpha=0.85, zorder=3)

    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, rotation=22, ha="right", fontsize=8)
    ax.set_ylabel("Response time (ms)", fontsize=9)
    ax.set_title("Latency by Endpoint (P50 / P95 / P99)", fontsize=10, loc="left", pad=8,
                 color=DARK, fontweight="bold")
    ax.legend(fontsize=8, frameon=True, framealpha=0.9, edgecolor=BORDER)
    ax.grid(axis="y", color="#F3F4F6", linewidth=0.8, zorder=0)
    plt.tight_layout(pad=1.2)
    return fig


def _error_rate_bar_chart(metrics: dict) -> plt.Figure:
    endpoints = metrics.get("endpoints", {})
    if not endpoints:
        fig, ax = plt.subplots(figsize=(6, 3))
        _apply_light_style(fig, ax)
        ax.text(0.5, 0.5, "No endpoint data", ha="center", va="center", color="#9CA3AF")
        ax.axis("off")
        return fig

    ordered = sorted(endpoints.items(), key=lambda x: x[1].get("error_rate_pct", 0), reverse=True)
    labels  = [l for l, _ in ordered][:8]
    values  = [d.get("error_rate_pct", 0) for _, d in ordered][:8]
    bar_colors = [RED if v >= 5 else AMBER if v >= 1 else GREEN for v in values]

    fig, ax = plt.subplots(figsize=(6.5, 4))
    _apply_light_style(fig, ax)
    bars = ax.barh(labels[::-1], values[::-1], color=bar_colors[::-1], alpha=0.85, zorder=3, height=0.6)
    for bar, val in zip(bars, values[::-1]):
        if val > 0:
            ax.text(bar.get_width() + 0.05, bar.get_y() + bar.get_height()/2,
                    f"{val:.1f}%", va="center", fontsize=7.5, color=GRAY)
    ax.set_xlabel("Error Rate (%)", fontsize=9)
    ax.set_title("Endpoint Error Rates", fontsize=10, loc="left", pad=8, color=DARK, fontweight="bold")
    ax.grid(axis="x", color="#F3F4F6", linewidth=0.8, zorder=0)
    plt.tight_layout(pad=1.2)
    return fig


def _latency_spread_chart(metrics: dict) -> plt.Figure:
    endpoints = metrics.get("endpoints", {})
    if not endpoints:
        fig, ax = plt.subplots(figsize=(9, 3))
        _apply_light_style(fig, ax)
        ax.text(0.5, 0.5, "No endpoint data", ha="center", va="center", color="#9CA3AF")
        ax.axis("off")
        return fig

    ordered = sorted(endpoints.items(), key=lambda x: x[1].get("p95_ms", 0), reverse=True)
    labels = [l for l, _ in ordered][:8]
    avg = [d.get("avg_ms", 0) for _, d in ordered][:8]
    p95 = [d.get("p95_ms", 0) for _, d in ordered][:8]
    p99 = [d.get("p99_ms", 0) for _, d in ordered][:8]

    fig, ax = plt.subplots(figsize=(13, 3.8))
    _apply_light_style(fig, ax)
    pos = list(range(len(labels)))
    ax.fill_between(pos, avg, p99, alpha=0.06, color=RED)
    ax.fill_between(pos, avg, p95, alpha=0.08, color=AMBER)
    ax.plot(pos, avg, marker="o", markersize=6, color=GREEN,  linewidth=2, label="Avg",  zorder=4)
    ax.plot(pos, p95, marker="s", markersize=5, color=AMBER,  linewidth=2, label="P95",  zorder=4)
    ax.plot(pos, p99, marker="^", markersize=5, color=RED,    linewidth=2, label="P99",  zorder=4)
    ax.set_xticks(pos)
    ax.set_xticklabels(labels, rotation=18, ha="right", fontsize=8)
    ax.set_ylabel("Latency (ms)", fontsize=9)
    ax.set_title("Latency Spread Across Endpoints", fontsize=10, loc="left", pad=8,
                 color=DARK, fontweight="bold")
    ax.legend(fontsize=8, frameon=True, framealpha=0.9, edgecolor=BORDER)
    plt.tight_layout(pad=1.2)
    return fig


def _error_pie_chart(metrics: dict) -> plt.Figure:
    errors = metrics.get("errors", {})
    fig, ax = plt.subplots(figsize=(4.5, 3.5))
    _apply_light_style(fig, ax)

    if not errors:
        ax.text(0.5, 0.5, "No errors\nrecorded", ha="center", va="center",
                color=GREEN, fontsize=11, fontweight="bold", transform=ax.transAxes)
        ax.axis("off")
        return fig

    codes   = list(errors.keys())
    counts  = [e["count"] for e in errors.values()]
    palette = [RED, AMBER, BLUE, PURPLE, GREEN]
    wedges, texts, autotexts = ax.pie(
        counts, labels=[f"HTTP {c}" for c in codes],
        colors=palette[:len(codes)], autopct="%1.0f%%",
        startangle=90, textprops={"fontsize": 8, "color": DARK},
        wedgeprops={"linewidth": 2, "edgecolor": "white"},
    )
    for at in autotexts:
        at.set_fontsize(8)
        at.set_color("white")
        at.set_fontweight("bold")
    ax.set_title("Error Distribution", fontsize=10, loc="left", pad=8, color=DARK, fontweight="bold")
    plt.tight_layout(pad=1.0)
    return fig


# ══════════════════════════════════════════════════════════════════════════════
# PAGE CHROME
# ══════════════════════════════════════════════════════════════════════════════

def _page_chrome(canvas_obj, doc):
    canvas_obj.saveState()
    w, h = A4

    # Purple top stripe
    canvas_obj.setFillColor(colors.HexColor(PURPLE))
    canvas_obj.rect(0, h - 0.6*cm, w, 0.6*cm, stroke=0, fill=1)

    # Bottom footer
    canvas_obj.setFillColor(colors.HexColor("#F9FAFB"))
    canvas_obj.rect(0, 0, w, 1.1*cm, stroke=0, fill=1)
    canvas_obj.setStrokeColor(colors.HexColor(BORDER))
    canvas_obj.setLineWidth(0.5)
    canvas_obj.line(0, 1.1*cm, w, 1.1*cm)

    canvas_obj.setFont("Helvetica", 8)
    canvas_obj.setFillColor(colors.HexColor(GRAY))
    canvas_obj.drawString(1.8*cm, 0.42*cm, "PerfAI Load Test Report  —  Confidential")
    canvas_obj.drawRightString(w - 1.8*cm, 0.42*cm, f"Page {doc.page}")

    canvas_obj.restoreState()


# ══════════════════════════════════════════════════════════════════════════════
# STYLE HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _build_styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "cover_title": ParagraphStyle("cover_title",
            fontSize=22, fontName="Helvetica-Bold",
            textColor=colors.HexColor(DARK), leading=26, spaceAfter=4),
        "small_label": ParagraphStyle("small_label",
            fontSize=9, textColor=colors.HexColor(GRAY),
            spaceAfter=2, leading=13),
        "h1": ParagraphStyle("h1",
            fontSize=16, fontName="Helvetica-Bold",
            textColor=colors.HexColor(DARK), spaceBefore=6, spaceAfter=4, leading=20),
        "h2_bold": ParagraphStyle("h2_bold",
            fontSize=11, fontName="Helvetica-Bold",
            textColor=colors.HexColor(DARK), spaceBefore=4, spaceAfter=4, leading=15),
        "body": ParagraphStyle("body",
            fontSize=9, textColor=colors.HexColor(DARK), leading=13, spaceAfter=3),
        "small": ParagraphStyle("small",
            fontSize=8, textColor=colors.HexColor(GRAY), leading=11),
    }


def _pdf_section_title(story, title: str):
    """Render a bold section heading with a purple left-bar accent — matches web report style."""
    row = [[
        Table(
            [[Paragraph("", ParagraphStyle("bar"))]],
            colWidths=[0.3*cm],
            style=TableStyle([
                ("BACKGROUND",    (0, 0), (-1, -1), PDF_PURPLE),
                ("TOPPADDING",    (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ("LEFTPADDING",   (0, 0), (-1, -1), 0),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
            ])
        ),
        Paragraph(f'<font size="14" color="{DARK}"><b>{title}</b></font>',
                  ParagraphStyle("st", leading=18, leftIndent=8)),
    ]]
    t = Table(row, colWidths=[0.45*cm, 16.95*cm])
    t.setStyle(TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
    ]))
    story.append(Spacer(1, 0.35*cm))
    story.append(t)
    story.append(Spacer(1, 0.08*cm))
    story.append(HRFlowable(width="100%", thickness=1.5, color=PDF_PURPLE, spaceAfter=0.25*cm))


def _purple_pill(text: str) -> Paragraph:
    return Paragraph(
        f'<font size="8" color="{PURPLE}"><b>{text}</b></font>',
        ParagraphStyle("pill",
            backColor=colors.HexColor(PURPLE_LIGHT),
            borderPadding=(3, 6, 3, 6),
            leading=11)
    )


def _label(text: str) -> Paragraph:
    return Paragraph(f'<font size="9" color="{GRAY}">{text}</font>',
                     ParagraphStyle("lbl", leading=13))


def _th(text: str) -> Paragraph:
    return Paragraph(f'<font size="8" color="{DARK}"><b>{text}</b></font>',
                     ParagraphStyle("th", leading=11))


def _td(text: str) -> Paragraph:
    return Paragraph(f'<font size="8" color="{DARK}">{text}</font>',
                     ParagraphStyle("td", leading=11))


def _stats_table_style(n_rows: int) -> TableStyle:
    cmds = [
        ("BACKGROUND",    (0, 0), (-1, 0),  colors.HexColor("#F9FAFB")),
        ("FONTSIZE",      (0, 0), (-1, -1), 8),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, colors.HexColor("#FAFAFA")]),
        ("GRID",          (0, 0), (-1, -1), 0.4, colors.HexColor(BORDER)),
        ("TOPPADDING",    (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW",     (0, 0), (-1, 0),  0.8, colors.HexColor(BORDER)),
    ]
    return TableStyle(cmds)


def _fig_to_image(fig: plt.Figure, width: float) -> Image:
    from PIL import Image as _PILImage
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor="white")
    buf.seek(0)
    pil_img = _PILImage.open(buf)
    w_px, h_px = pil_img.size
    height = width * (h_px / w_px)
    buf.seek(0)
    plt.close(fig)
    img = Image(buf, width=width, height=height)
    img.hAlign = "LEFT"
    return img


def _severity_rank(severity) -> int:
    return {"high": 0, "medium": 1, "low": 2}.get((severity or "").lower(), 3)


def _hex(color_obj) -> str:
    try:
        return f"#{int(color_obj.red*255):02X}{int(color_obj.green*255):02X}{int(color_obj.blue*255):02X}"
    except Exception:
        return GRAY
