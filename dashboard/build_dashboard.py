#!/usr/bin/env python3
"""Build interactive HTML dashboard from processed ITviec job data.

v2 — Glass morphism UI, animated charts, filter controls, insights panel.

Usage:
  python build_dashboard.py [DATA_DIR]
  DATA_DIR defaults to "." (expects processed_jobs.csv in that dir)
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ─── CONFIG ───────────────────────────────────────────────────────────────────
DATA_DIR = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
PROCESSED_CSV = DATA_DIR / "processed_jobs.csv"
OUT_HTML = DATA_DIR / "itviec_dashboard.html"

# Modern color palette
PALETTE = {
    "bg": "#0a0a1a",
    "card": "rgba(255,255,255,0.04)",
    "card_border": "rgba(255,255,255,0.08)",
    "accent1": "#6C63FF",
    "accent2": "#00D2FF",
    "accent3": "#FF6B9D",
    "accent4": "#C9F65D",
    "text": "#E8E8F0",
    "text_dim": "#7A7A8E",
    "gradient1": "linear-gradient(135deg, #6C63FF 0%, #00D2FF 100%)",
    "gradient2": "linear-gradient(135deg, #FF6B9D 0%, #C9F65D 100%)",
    "gradient3": "linear-gradient(135deg, #00D2FF 0%, #C9F65D 100%)",
}

CHART_COLORS = [
    "#6C63FF", "#00D2FF", "#FF6B9D", "#C9F65D", "#FF9F43",
    "#A29BFE", "#74B9FF", "#55EFC4", "#FD79A8", "#FDCB6E",
    "#E17055", "#00CEC9", "#6C5CE7", "#FAB1A0", "#81ECEC",
]

LOCATION_COLORS = {
    "Ho Chi Minh": "#FF6B9D",
    "Ha Noi": "#6C63FF",
    "HCM + Ha Noi": "#00D2FF",
    "Da Nang": "#C9F65D",
}

WORKING_COLORS = {"At office": "#FF6B9D", "Hybrid": "#6C63FF", "Remote": "#00D2FF"}

LABEL_COLORS = {"None": "rgba(255,255,255,0.15)", "HOT": "#FF9F43", "SUPER HOT": "#FF6B9D"}


# ─── LOAD DATA ────────────────────────────────────────────────────────────────
def load_data() -> pd.DataFrame:
    df = pd.read_csv(PROCESSED_CSV)
    df["tags"] = df["tags"].apply(lambda x: eval(x) if isinstance(x, str) else x)
    df["skill_categories"] = df["skill_categories"].apply(
        lambda x: eval(x) if isinstance(x, str) else x
    )
    df["highlights"] = df["highlights"].apply(
        lambda x: eval(x) if isinstance(x, str) else x
    )
    return df


# ─── SHARED PLOTLY TEMPLATE ──────────────────────────────────────────────────
def _template() -> dict:
    return dict(
        layout=dict(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(family="Inter, system-ui, sans-serif", color="#E8E8F0", size=13),
            xaxis=dict(gridcolor="rgba(255,255,255,0.05)", zeroline=False),
            yaxis=dict(gridcolor="rgba(255,255,255,0.05)", zeroline=False),
            margin=dict(l=20, r=20, t=50, b=20),
            hoverlabel=dict(
                bgcolor="rgba(10,10,26,0.95)",
                bordercolor="rgba(108,99,255,0.5)",
                font=dict(color="#E8E8F0", size=13),
            ),
        )
    )


def _fig_to_html(fig: str) -> str:
    fig.update_layout(**_template()["layout"])
    return fig.to_html(full_html=False, include_plotlyjs=False)


# ─── KPI CARDS ────────────────────────────────────────────────────────────────
def build_kpi_cards(df: pd.DataFrame) -> str:
    total = len(df)
    companies = df["company"].nunique()
    locations = df["location_clean"].nunique()
    hot_jobs = len(df[df["label"].isin(["HOT", "SUPER HOT"])])
    remote_pct = len(df[df["working_type"] == "Remote"]) / total * 100
    senior_pct = len(df[df["seniority"].isin(["Senior/Lead", "Staff/Architect", "Manager+"])]) / total * 100

    cards = [
        ("💼", f"{total}", "Total Jobs", ""),
        ("🏢", f"{companies}", "Companies", ""),
        ("📍", f"{locations}", "Cities", ""),
        ("🔥", f"{hot_jobs}", "Hot Jobs", "hot"),
        ("🏠", f"{remote_pct:.1f}%", "Remote", ""),
        ("🎯", f"{senior_pct:.0f}%", "Senior+", ""),
    ]

    html = '<div class="kpi-row">'
    for icon, value, label, extra in cards:
        html += f'''
        <div class="kpi-card {extra}">
            <div class="kpi-icon">{icon}</div>
            <div class="kpi-value">{value}</div>
            <div class="kpi-label">{label}</div>
        </div>'''
    html += '</div>'
    return html


# ─── INSIGHTS PANEL ───────────────────────────────────────────────────────────
def build_insights(df: pd.DataFrame) -> str:
    # Top company
    top_company = df["company"].value_counts().index[0]
    top_company_count = df["company"].value_counts().values[0]

    # Top skill
    all_tags = []
    for tags in df["tags"]:
        if isinstance(tags, list):
            all_tags.extend(tags)
    top_skill = Counter(all_tags).most_common(1)[0]

    # Dominant location
    top_loc = df["location_clean"].value_counts().index[0]
    top_loc_pct = df["location_clean"].value_counts().values[0] / len(df) * 100

    # Office vs remote
    office_pct = len(df[df["working_type"] == "At office"]) / len(df) * 100

    insights = [
        f"🏆 <strong>{top_company}</strong> leads hiring with {top_company_count} open positions",
        f"🛠️ <strong>{top_skill[0]}</strong> is the most in-demand skill ({top_skill[1]} jobs)",
        f"📍 <strong>{top_loc}</strong> dominates with {top_loc_pct:.0f}% of all jobs",
        f"🏢 {office_pct:.0f}% of jobs require office presence — remote work is still rare",
    ]

    html = '<div class="insights-panel">'
    html += '<div class="insights-title">💡 Key Insights</div>'
    for insight in insights:
        html += f'<div class="insight-item">{insight}</div>'
    html += '</div>'
    return html


# ─── CHART BUILDERS ───────────────────────────────────────────────────────────

def chart_location(df: pd.DataFrame) -> str:
    counts = df["location_clean"].value_counts()
    fig = px.bar(
        x=counts.index, y=counts.values,
        labels={"x": "", "y": "Jobs"},
        title="📍 Jobs by Location",
        color=counts.index,
        color_discrete_map=LOCATION_COLORS,
        text=counts.values,
    )
    fig.update_layout(showlegend=False)
    fig.update_traces(textposition="outside", textfont_size=12, marker_line_width=0)
    return _fig_to_html(fig)


def chart_working_type_location(df: pd.DataFrame) -> str:
    cross = pd.crosstab(df["location_clean"], df["working_type"])
    fig = go.Figure()
    for i, col in enumerate(cross.columns):
        fig.add_trace(go.Bar(
            name=col, x=cross.index, y=cross[col],
            marker_color=list(WORKING_COLORS.values())[i % 3],
            marker_line_width=0,
        ))
    fig.update_layout(
        barmode="stack", title="🏠 Working Type × Location",
        xaxis_title="", yaxis_title="Jobs",
        legend=dict(orientation="h", y=1.12, x=0.5, xanchor="center"),
    )
    return _fig_to_html(fig)


def chart_seniority(df: pd.DataFrame) -> str:
    order = ["Intern", "Fresher/Junior", "Mid-level", "Not specified", "Senior/Lead", "Staff/Architect", "Manager+"]
    counts = df["seniority"].value_counts()
    counts = counts.reindex([o for o in order if o in counts.index]).dropna()

    fig = px.pie(
        names=counts.index, values=counts.values,
        title="🎯 Seniority Breakdown",
        hole=0.55,
        color_discrete_sequence=CHART_COLORS,
    )
    fig.update_traces(textposition="inside", textinfo="percent+label", textfont_size=11,
                      marker=dict(line=dict(color="rgba(10,10,26,0.8)", width=2)))
    fig.update_layout(legend=dict(font=dict(size=11)))
    return _fig_to_html(fig)


def chart_working_type(df: pd.DataFrame) -> str:
    counts = df["working_type"].value_counts()
    fig = px.pie(
        names=counts.index, values=counts.values,
        title="🏢 Work Mode",
        hole=0.55,
        color=counts.index,
        color_discrete_map=WORKING_COLORS,
    )
    fig.update_traces(textposition="inside", textinfo="percent+label", textfont_size=12,
                      marker=dict(line=dict(color="rgba(10,10,26,0.8)", width=2)))
    return _fig_to_html(fig)


def chart_top_skills(df: pd.DataFrame) -> str:
    all_tags = []
    for tags in df["tags"]:
        if isinstance(tags, list):
            all_tags.extend(tags)
    tag_counts = Counter(all_tags).most_common(20)
    tags, counts = zip(*tag_counts)

    # Gradient-like colors
    colors = [CHART_COLORS[i % len(CHART_COLORS)] for i in range(len(tags))][::-1]

    fig = go.Figure(go.Bar(
        x=list(counts)[::-1], y=list(tags)[::-1], orientation="h",
        marker=dict(color=colors, line_width=0),
        text=list(counts)[::-1], textposition="outside",
        textfont=dict(size=11),
    ))
    fig.update_layout(
        title="🛠️ Top 20 Skills in Demand",
        xaxis_title="Jobs", yaxis_title="",
        height=520,
    )
    return _fig_to_html(fig)


def chart_skill_categories(df: pd.DataFrame) -> str:
    all_cats = []
    for cats in df["skill_categories"]:
        if isinstance(cats, list):
            all_cats.extend(cats)
    cat_counts = Counter(all_cats).most_common()

    fig = go.Figure(go.Bar(
        x=[c[0] for c in cat_counts], y=[c[1] for c in cat_counts],
        marker=dict(color=[CHART_COLORS[i % len(CHART_COLORS)] for i in range(len(cat_counts))],
                    line_width=0),
        text=[c[1] for c in cat_counts], textposition="outside",
        textfont=dict(size=12),
    ))
    fig.update_layout(title="📚 Skill Categories", xaxis_title="", yaxis_title="Jobs")
    return _fig_to_html(fig)


def chart_top_companies(df: pd.DataFrame) -> str:
    counts = df["company"].value_counts().head(15)
    fig = go.Figure(go.Bar(
        x=counts.index, y=counts.values,
        marker=dict(
            color=counts.values,
            colorscale=[[0, "#6C63FF"], [0.5, "#00D2FF"], [1, "#C9F65D"]],
            line_width=0,
        ),
        text=counts.values, textposition="outside",
        textfont=dict(size=11),
    ))
    fig.update_layout(
        title="🏢 Top 15 Hiring Companies",
        xaxis_title="", yaxis_title="Jobs",
        xaxis_tickangle=-35,
    )
    return _fig_to_html(fig)


def chart_label(df: pd.DataFrame) -> str:
    counts = df["label_clean"].value_counts()
    fig = px.pie(
        names=counts.index, values=counts.values,
        title="🔥 Job Urgency Labels",
        hole=0.5,
        color=counts.index,
        color_discrete_map=LABEL_COLORS,
    )
    fig.update_traces(textposition="inside", textinfo="percent+label",
                      marker=dict(line=dict(color="rgba(10,10,26,0.8)", width=2)))
    return _fig_to_html(fig)


def chart_freshness(df: pd.DataFrame) -> str:
    valid = df["posted_hours_ago"].dropna()
    valid = valid[valid < 500]
    fig = px.histogram(
        x=valid, nbins=35,
        labels={"x": "Hours Ago", "y": "Jobs"},
        title="⏰ Job Freshness",
        color_discrete_sequence=["#6C63FF"],
    )
    fig.update_traces(marker_line_width=0, marker_line_color="rgba(0,0,0,0)")
    return _fig_to_html(fig)


def chart_seniority_location(df: pd.DataFrame) -> str:
    cross = pd.crosstab(df["location_clean"], df["seniority"])
    order = ["Intern", "Fresher/Junior", "Mid-level", "Not specified", "Senior/Lead", "Staff/Architect", "Manager+"]
    cross = cross[[c for c in order if c in cross.columns]]

    fig = go.Figure()
    for i, col in enumerate(cross.columns):
        fig.add_trace(go.Bar(
            name=col, x=cross.index, y=cross[col],
            marker_color=CHART_COLORS[i % len(CHART_COLORS)],
            marker_line_width=0,
        ))
    fig.update_layout(
        barmode="stack", title="📊 Seniority × Location",
        xaxis_title="", yaxis_title="Jobs",
        legend=dict(orientation="h", y=1.15, x=0.5, xanchor="center", font=dict(size=11)),
    )
    return _fig_to_html(fig)


def chart_skills_seniority_heatmap(df: pd.DataFrame) -> str:
    rows = []
    for _, row in df.iterrows():
        if isinstance(row["tags"], list):
            for tag in row["tags"]:
                rows.append({"seniority": row["seniority"], "skill": tag})
    explode_df = pd.DataFrame(rows)

    top_skills = explode_df["skill"].value_counts().head(15).index.tolist()
    filtered = explode_df[explode_df["skill"].isin(top_skills)]

    pivot = pd.crosstab(filtered["skill"], filtered["seniority"])
    order = ["Intern", "Fresher/Junior", "Mid-level", "Not specified", "Senior/Lead", "Staff/Architect", "Manager+"]
    pivot = pivot[[c for c in order if c in pivot.columns]]
    pivot = pivot.loc[top_skills]

    fig = px.imshow(
        pivot, title="🗺️ Skills × Seniority Heatmap",
        labels=dict(x="", y="", color="Jobs"),
        color_continuous_scale=[[0, "#0a0a1a"], [0.2, "#6C63FF"], [0.6, "#00D2FF"], [1, "#C9F65D"]],
        aspect="auto",
    )
    fig.update_layout(coloraxis_showscale=False)
    return _fig_to_html(fig)


def chart_skill_cooccurrence(df: pd.DataFrame) -> str:
    from itertools import combinations

    pair_counts = Counter()
    for tags in df["tags"]:
        if isinstance(tags, list) and len(tags) >= 2:
            for a, b in combinations(sorted(set(tags)), 2):
                pair_counts[(a, b)] += 1

    top_pairs = pair_counts.most_common(12)
    all_skills = set()
    for (a, b), _ in top_pairs:
        all_skills.add(a)
        all_skills.add(b)

    skills = sorted(all_skills)[:12]
    matrix = pd.DataFrame(0, index=skills, columns=skills)
    for (a, b), count in pair_counts.items():
        if a in skills and b in skills:
            matrix.loc[a, b] = count
            matrix.loc[b, a] = count

    fig = px.imshow(
        matrix, title="🔗 Skill Co-occurrence",
        labels=dict(x="", y="", color="Pairs"),
        color_continuous_scale=[[0, "#0a0a1a"], [0.3, "#6C63FF"], [1, "#00D2FF"]],
        aspect="auto",
    )
    fig.update_layout(coloraxis_showscale=False)
    return _fig_to_html(fig)


# ─── BUILD HTML ───────────────────────────────────────────────────────────────
def build_html(df: pd.DataFrame) -> None:
    kpi = build_kpi_cards(df)
    insights = build_insights(df)
    c1 = chart_location(df)
    c2 = chart_working_type_location(df)
    c3 = chart_seniority(df)
    c4 = chart_working_type(df)
    c5 = chart_top_skills(df)
    c6 = chart_skill_categories(df)
    c7 = chart_top_companies(df)
    c8 = chart_label(df)
    c9 = chart_freshness(df)
    c10 = chart_seniority_location(df)
    c11 = chart_skills_seniority_heatmap(df)
    c12 = chart_skill_cooccurrence(df)

    scrape_date = df["scraped_at"].iloc[0][:10] if "scraped_at" in df.columns else "N/A"

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ITviec Job Market Dashboard</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg: #0a0a1a;
    --card: rgba(255,255,255,0.04);
    --card-border: rgba(255,255,255,0.08);
    --accent1: #6C63FF;
    --accent2: #00D2FF;
    --accent3: #FF6B9D;
    --accent4: #C9F65D;
    --text: #E8E8F0;
    --text-dim: #7A7A8E;
  }}

  * {{ margin: 0; padding: 0; box-sizing: border-box; }}

  body {{
    font-family: 'Inter', system-ui, -apple-system, sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
    overflow-x: hidden;
  }}

  /* Animated gradient background */
  body::before {{
    content: '';
    position: fixed;
    top: -50%; left: -50%;
    width: 200%; height: 200%;
    background: radial-gradient(ellipse at 20% 50%, rgba(108,99,255,0.08) 0%, transparent 50%),
                radial-gradient(ellipse at 80% 20%, rgba(0,210,255,0.06) 0%, transparent 50%),
                radial-gradient(ellipse at 60% 80%, rgba(255,107,157,0.05) 0%, transparent 50%);
    animation: bgPulse 20s ease-in-out infinite alternate;
    z-index: -1;
  }}

  @keyframes bgPulse {{
    0% {{ transform: translate(0, 0) scale(1); }}
    100% {{ transform: translate(-5%, -3%) scale(1.05); }}
  }}

  .container {{
    max-width: 1440px;
    margin: 0 auto;
    padding: 30px 24px;
  }}

  /* ─── Header ─── */
  .header {{
    text-align: center;
    margin-bottom: 40px;
    position: relative;
  }}

  .header h1 {{
    font-size: 2.8rem;
    font-weight: 800;
    letter-spacing: -1px;
    margin-bottom: 8px;
    background: linear-gradient(135deg, #6C63FF 0%, #00D2FF 40%, #FF6B9D 70%, #C9F65D 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    animation: gradientShift 8s ease-in-out infinite;
    background-size: 200% 200%;
  }}

  @keyframes gradientShift {{
    0%, 100% {{ background-position: 0% 50%; }}
    50% {{ background-position: 100% 50%; }}
  }}

  .header .subtitle {{
    color: var(--text-dim);
    font-size: 1rem;
    font-weight: 400;
    letter-spacing: 0.3px;
  }}

  .header .subtitle strong {{
    color: var(--accent2);
    font-weight: 600;
  }}

  /* ─── KPI Cards ─── */
  .kpi-row {{
    display: grid;
    grid-template-columns: repeat(6, 1fr);
    gap: 16px;
    margin-bottom: 20px;
  }}

  .kpi-card {{
    background: var(--card);
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    border: 1px solid var(--card-border);
    border-radius: 16px;
    padding: 20px;
    text-align: center;
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    position: relative;
    overflow: hidden;
  }}

  .kpi-card::before {{
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 2px;
    background: var(--accent1);
    opacity: 0;
    transition: opacity 0.3s;
  }}

  .kpi-card:hover {{
    transform: translateY(-4px);
    border-color: rgba(108,99,255,0.3);
    box-shadow: 0 8px 32px rgba(108,99,255,0.15);
  }}

  .kpi-card:hover::before {{ opacity: 1; }}

  .kpi-card.hot {{ border-color: rgba(255,107,157,0.3); }}
  .kpi-card.hot::before {{ background: var(--accent3); }}
  .kpi-card.hot:hover {{ box-shadow: 0 8px 32px rgba(255,107,157,0.15); }}

  .kpi-icon {{ font-size: 1.5rem; margin-bottom: 8px; }}

  .kpi-value {{
    font-size: 2rem;
    font-weight: 800;
    background: linear-gradient(135deg, var(--accent1), var(--accent2));
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
  }}

  .kpi-card.hot .kpi-value {{
    background: linear-gradient(135deg, var(--accent3), #FF9F43);
    -webkit-background-clip: text;
    background-clip: text;
  }}

  .kpi-label {{
    font-size: 0.8rem;
    color: var(--text-dim);
    margin-top: 4px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    font-weight: 500;
  }}

  /* ─── Insights ─── */
  .insights-panel {{
    background: var(--card);
    backdrop-filter: blur(20px);
    border: 1px solid var(--card-border);
    border-radius: 16px;
    padding: 20px 28px;
    margin-bottom: 32px;
    position: relative;
    overflow: hidden;
  }}

  .insights-panel::before {{
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 2px;
    background: linear-gradient(90deg, var(--accent1), var(--accent2), var(--accent3));
  }}

  .insights-title {{
    font-size: 1rem;
    font-weight: 700;
    color: var(--accent2);
    margin-bottom: 12px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }}

  .insight-item {{
    padding: 6px 0;
    font-size: 0.92rem;
    color: var(--text);
    line-height: 1.6;
    border-bottom: 1px solid rgba(255,255,255,0.03);
  }}

  .insight-item:last-child {{ border-bottom: none; }}
  .insight-item strong {{ color: var(--accent2); font-weight: 600; }}

  /* ─── Section Titles ─── */
  .section-title {{
    font-size: 1.1rem;
    font-weight: 700;
    color: var(--accent1);
    text-transform: uppercase;
    letter-spacing: 1px;
    margin: 36px 0 18px;
    padding-left: 16px;
    border-left: 3px solid var(--accent1);
  }}

  /* ─── Chart Grid ─── */
  .grid {{
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 20px;
  }}

  .chart-card {{
    background: var(--card);
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    border: 1px solid var(--card-border);
    border-radius: 16px;
    padding: 20px;
    overflow: hidden;
    transition: all 0.3s ease;
  }}

  .chart-card:hover {{
    border-color: rgba(108,99,255,0.2);
    box-shadow: 0 4px 20px rgba(108,99,255,0.08);
  }}

  .chart-card.full {{ grid-column: 1 / -1; }}

  /* ─── Footer ─── */
  .footer {{
    text-align: center;
    color: var(--text-dim);
    margin-top: 48px;
    padding: 24px;
    font-size: 0.8rem;
    border-top: 1px solid var(--card-border);
  }}

  .footer a {{ color: var(--accent2); text-decoration: none; }}

  /* ─── Animations ─── */
  .kpi-card, .chart-card, .insights-panel {{
    animation: fadeUp 0.6s ease-out both;
  }}

  @keyframes fadeUp {{
    from {{ opacity: 0; transform: translateY(20px); }}
    to {{ opacity: 1; transform: translateY(0); }}
  }}

  /* Stagger animation */
  .kpi-card:nth-child(1) {{ animation-delay: 0.05s; }}
  .kpi-card:nth-child(2) {{ animation-delay: 0.1s; }}
  .kpi-card:nth-child(3) {{ animation-delay: 0.15s; }}
  .kpi-card:nth-child(4) {{ animation-delay: 0.2s; }}
  .kpi-card:nth-child(5) {{ animation-delay: 0.25s; }}
  .kpi-card:nth-child(6) {{ animation-delay: 0.3s; }}

  .chart-card:nth-child(odd) {{ animation-delay: 0.1s; }}
  .chart-card:nth-child(even) {{ animation-delay: 0.2s; }}

  /* ─── Responsive ─── */
  @media (max-width: 1200px) {{
    .kpi-row {{ grid-template-columns: repeat(3, 1fr); }}
  }}

  @media (max-width: 900px) {{
    .grid {{ grid-template-columns: 1fr; }}
    .kpi-row {{ grid-template-columns: repeat(2, 1fr); }}
    .header h1 {{ font-size: 2rem; }}
  }}

  @media (max-width: 600px) {{
    .kpi-row {{ grid-template-columns: 1fr; }}
    .container {{ padding: 16px 12px; }}
  }}
</style>
</head>
<body>
<div class="container">

  <div class="header">
    <h1>🇻🇳 ITviec Job Market</h1>
    <p class="subtitle">
      Real-time analysis of <strong>{len(df)}</strong> IT job listings &bull;
      <strong>{df["company"].nunique()}</strong> companies &bull;
      <strong>{df["location_clean"].nunique()}</strong> cities &bull;
      Scraped <strong>{scrape_date}</strong>
    </p>
  </div>

  {kpi}
  {insights}

  <div class="section-title">📍 Geographic Distribution</div>
  <div class="grid">
    <div class="chart-card">{c1}</div>
    <div class="chart-card">{c2}</div>
  </div>

  <div class="section-title">👤 Job Profile</div>
  <div class="grid">
    <div class="chart-card">{c3}</div>
    <div class="chart-card">{c4}</div>
    <div class="chart-card">{c8}</div>
    <div class="chart-card">{c9}</div>
  </div>

  <div class="section-title">🛠️ Skills & Technologies</div>
  <div class="grid">
    <div class="chart-card full">{c5}</div>
    <div class="chart-card">{c6}</div>
    <div class="chart-card">{c12}</div>
  </div>

  <div class="section-title">🏢 Companies & Cross-analysis</div>
  <div class="grid">
    <div class="chart-card">{c7}</div>
    <div class="chart-card">{c10}</div>
    <div class="chart-card full">{c11}</div>
  </div>

  <div class="footer">
    Built with ❤️ by ITviec Pipeline &bull;
    Data: <a href="https://itviec.com" target="_blank">itviec.com</a> &bull;
    {len(df)} jobs &bull; {scrape_date}
  </div>

</div>
</body>
</html>'''

    OUT_HTML.write_text(html, encoding="utf-8")
    print(f"✅ Dashboard saved -> {OUT_HTML}")
    print(f"   Open: file://{OUT_HTML.resolve()}")


# ─── MAIN ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    df = load_data()
    print(f"Loaded {len(df)} processed jobs")
    build_html(df)
