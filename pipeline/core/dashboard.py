"""Dashboard HTML — 1 shell + 1 bộ chart primitive cho mọi source.

Trước đây mỗi source có 1 hàm build + 1 template HTML riêng (trùng CSS, trùng
logic chart). Nay: source chỉ **khai báo** `Section`/`ChartSpec`/`KpiSpec`,
toàn bộ render nằm ở đây.

Chart nào thiếu cột (vd topcv không có `working_type`) sẽ tự bị bỏ qua, nên
cùng 1 danh sách spec có thể chạy cho nhiều source.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path

import pandas as pd

from pipeline.core.snapshot import atomic_write_text
from pipeline.core.transform import SENIORITY_ORDER

logger = logging.getLogger(__name__)

CHART_COLORS = [
    "#6C63FF", "#00D2FF", "#FF6B9D", "#C9F65D", "#FF9F43",
    "#A29BFE", "#74B9FF", "#55EFC4", "#FD79A8", "#FDCB6E",
    "#E17055", "#00CEC9", "#6C5CE7", "#FAB1A0", "#81ECEC",
]
LOCATION_COLORS = {
    "Ho Chi Minh": "#FF6B9D", "Ha Noi": "#6C63FF",
    "HCM + Ha Noi": "#00D2FF", "Da Nang": "#C9F65D",
}
WORKING_COLORS = {"At office": "#FF6B9D", "Hybrid": "#6C63FF", "Remote": "#00D2FF"}
LABEL_COLORS = {"None": "rgba(255,255,255,0.15)", "HOT": "#FF9F43", "SUPER HOT": "#FF6B9D"}

#: Ngưỡng cấp bậc được coi là "senior+" cho KPI.
SENIOR_PLUS = ("Senior/Lead", "Staff/Architect", "Manager+")


# ─── SPEC ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ChartSpec:
    """Khai báo 1 chart. `kind` quyết định builder nào được dùng."""

    kind: str                 # bar_h | bar_v | pie | stacked | hist | heatmap | cooccurrence
    title: str
    column: str               # cột chính (trục/category)
    second: str | None = None  # cột thứ 2 (stacked/heatmap)
    top: int = 15
    full: bool = False        # chiếm full width
    height: int | None = None
    list_column: bool = False  # cột chứa list → explode trước khi đếm


@dataclass(frozen=True)
class Section:
    """Nhóm chart hiển thị cạnh nhau."""

    title: str
    charts: tuple[ChartSpec, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class KpiSpec:
    """Khai báo 1 KPI card.

    kind:
        count        — tổng số row
        nunique      — số giá trị distinct của `column`
        nunique_list — số giá trị distinct sau khi explode cột list
        share        — % row có `column` thuộc `values` (list_column → giao nhau)
        sum_true     — số row có `column` truthy
    """

    icon: str
    label: str
    kind: str
    column: str = ""
    values: tuple[str, ...] = ()
    flag: str = ""            # class CSS thêm cho card (vd "hot")
    list_column: bool = False


# ─── CHART PRIMITIVES ────────────────────────────────────────────────────────


def _plotly_layout() -> dict:
    return dict(
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


def _fig_html(fig) -> str:
    fig.update_layout(**_plotly_layout())
    return fig.to_html(full_html=False, include_plotlyjs=False)


def _series(df: pd.DataFrame, spec: ChartSpec) -> pd.Series:
    """Value counts cho cột chính (explode nếu là cột list)."""
    col = df[spec.column].dropna()
    if spec.list_column:
        values = [item for items in col if isinstance(items, list) for item in items]
        return pd.Series(Counter(values))
    return col.astype(str).value_counts()


def _bar_h(df: pd.DataFrame, spec: ChartSpec) -> str | None:
    counts = _series(df, spec).head(spec.top)
    if counts.empty:
        return None
    import plotly.graph_objects as go

    pairs = list(zip(counts.index, counts.values))[::-1]
    labels, values = [p[0] for p in pairs], [p[1] for p in pairs]
    fig = go.Figure(go.Bar(
        x=values, y=labels, orientation="h",
        marker=dict(color=[CHART_COLORS[i % len(CHART_COLORS)] for i in range(len(labels))], line_width=0),
        text=values, textposition="outside", textfont=dict(size=11),
    ))
    fig.update_layout(title=spec.title, xaxis_title="Jobs", yaxis_title="",
                      height=spec.height or max(360, 26 * len(labels) + 120))
    return _fig_html(fig)


def _bar_v(df: pd.DataFrame, spec: ChartSpec) -> str | None:
    counts = _series(df, spec).head(spec.top)
    if counts.empty:
        return None
    import plotly.graph_objects as go

    fig = go.Figure(go.Bar(
        x=list(counts.index), y=list(counts.values),
        marker=dict(color=list(counts.values),
                    colorscale=[[0, "#6C63FF"], [0.5, "#00D2FF"], [1, "#C9F65D"]], line_width=0),
        text=list(counts.values), textposition="outside", textfont=dict(size=11),
    ))
    fig.update_layout(title=spec.title, xaxis_title="", yaxis_title="Jobs",
                      xaxis_tickangle=-35, height=spec.height or 420)
    return _fig_html(fig)


def _pie(df: pd.DataFrame, spec: ChartSpec) -> str | None:
    counts = _series(df, spec).head(spec.top)
    if counts.empty:
        return None
    import plotly.express as px

    color_map = {"location_clean": LOCATION_COLORS, "working_type": WORKING_COLORS,
                 "label_clean": LABEL_COLORS}.get(spec.column)
    fig = px.pie(names=list(counts.index), values=list(counts.values), title=spec.title,
                 hole=0.55, color=list(counts.index) if color_map else None,
                 color_discrete_map=color_map,
                 color_discrete_sequence=None if color_map else CHART_COLORS)
    fig.update_traces(textposition="inside", textinfo="percent+label", textfont_size=11,
                      marker=dict(line=dict(color="rgba(10,10,26,0.8)", width=2)))
    fig.update_layout(height=spec.height or 420, legend=dict(font=dict(size=11)))
    return _fig_html(fig)


def _order_seniority(index) -> list[str]:
    ordered = [s for s in SENIORITY_ORDER if s in set(index)]
    return ordered or list(index)


def _stacked(df: pd.DataFrame, spec: ChartSpec) -> str | None:
    if not spec.second or spec.second not in df.columns:
        return None
    import plotly.graph_objects as go

    cross = pd.crosstab(df[spec.column], df[spec.second])
    if cross.empty:
        return None
    if spec.second == "seniority":
        cross = cross[[c for c in _order_seniority(cross.columns)]]
    fig = go.Figure()
    for i, col in enumerate(cross.columns):
        fig.add_trace(go.Bar(name=str(col), x=cross.index, y=cross[col],
                             marker_color=CHART_COLORS[i % len(CHART_COLORS)], marker_line_width=0))
    fig.update_layout(barmode="stack", title=spec.title, xaxis_title="", yaxis_title="Jobs",
                      height=spec.height or 420,
                      legend=dict(orientation="h", y=1.15, x=0.5, xanchor="center", font=dict(size=11)))
    return _fig_html(fig)


def _hist(df: pd.DataFrame, spec: ChartSpec) -> str | None:
    import plotly.express as px

    values = pd.to_numeric(df[spec.column], errors="coerce").dropna()
    values = values[values < 500]
    if values.empty:
        return None
    fig = px.histogram(x=values, nbins=35, labels={"x": "Hours Ago", "y": "Jobs"},
                       title=spec.title, color_discrete_sequence=["#6C63FF"])
    fig.update_traces(marker_line_width=0, marker_line_color="rgba(0,0,0,0)")
    fig.update_layout(height=spec.height or 420)
    return _fig_html(fig)


def _heatmap(df: pd.DataFrame, spec: ChartSpec) -> str | None:
    if not spec.second or spec.second not in df.columns:
        return None
    import plotly.express as px

    rows = [
        {spec.second: r[spec.second], "_item": item}
        for _, r in df.iterrows()
        if isinstance(r[spec.column], list)
        for item in r[spec.column]
    ]
    if not rows:
        return None
    edf = pd.DataFrame(rows)
    top = edf["_item"].value_counts().head(spec.top).index.tolist()
    pivot = pd.crosstab(edf["_item"], edf[spec.second])
    pivot = pivot.reindex(index=top).dropna(how="all")
    if spec.second == "seniority":
        pivot = pivot[[c for c in _order_seniority(pivot.columns)]]
    fig = px.imshow(pivot, title=spec.title, labels=dict(x="", y="", color="Jobs"),
                    color_continuous_scale=[[0, "#0a0a1a"], [0.2, "#6C63FF"], [0.6, "#00D2FF"], [1, "#C9F65D"]],
                    aspect="auto")
    fig.update_layout(coloraxis_showscale=False, height=spec.height or 520)
    return _fig_html(fig)


def _cooccurrence(df: pd.DataFrame, spec: ChartSpec) -> str | None:
    import plotly.express as px

    pair_counts: Counter = Counter()
    for items in df[spec.column].dropna():
        if isinstance(items, list) and len(items) >= 2:
            for a, b in combinations(sorted(set(items)), 2):
                pair_counts[(a, b)] += 1
    top_pairs = pair_counts.most_common(spec.top)
    if not top_pairs:
        return None
    skills = sorted({s for (a, b), _ in top_pairs for s in (a, b)})[:12]
    matrix = pd.DataFrame(0, index=skills, columns=skills)
    for (a, b), count in pair_counts.items():
        if a in skills and b in skills:
            matrix.loc[a, b] = count
            matrix.loc[b, a] = count
    fig = px.imshow(matrix, title=spec.title, labels=dict(x="", y="", color="Pairs"),
                    color_continuous_scale=[[0, "#0a0a1a"], [0.3, "#6C63FF"], [1, "#00D2FF"]], aspect="auto")
    fig.update_layout(coloraxis_showscale=False, height=spec.height or 520)
    return _fig_html(fig)


_BUILDERS = {
    "bar_h": _bar_h,
    "bar_v": _bar_v,
    "pie": _pie,
    "stacked": _stacked,
    "hist": _hist,
    "heatmap": _heatmap,
    "cooccurrence": _cooccurrence,
}


def build_chart(df: pd.DataFrame, spec: ChartSpec) -> str | None:
    """Render 1 chart; trả None nếu source không có dữ liệu/cột tương ứng."""
    builder = _BUILDERS.get(spec.kind)
    if builder is None:
        logger.warning("ChartSpec.kind không hợp lệ: %s", spec.kind)
        return None
    if spec.column not in df.columns:
        logger.debug("Bỏ chart %s: thiếu cột %s", spec.title, spec.column)
        return None
    try:
        return builder(df, spec)
    except Exception:  # noqa: BLE001 — 1 chart lỗi không được làm chết dashboard
        logger.exception("Chart %s lỗi — bỏ qua", spec.title)
        return None


# ─── KPI + INSIGHTS ──────────────────────────────────────────────────────────


def _kpi_value(df: pd.DataFrame, spec: KpiSpec) -> str | None:
    if spec.kind == "count":
        return f"{len(df)}"
    if not spec.column or spec.column not in df.columns:
        return None
    if spec.kind == "nunique":
        return f"{df[spec.column].nunique()}"
    if spec.kind == "nunique_list":
        values = [item for items in df[spec.column].dropna() if isinstance(items, list) for item in items]
        return f"{len(set(values))}"
    if spec.kind == "sum_true":
        return f"{int(df[spec.column].fillna(False).astype(bool).sum())}"
    if spec.kind == "share":
        if spec.list_column:
            mask = df[spec.column].apply(
                lambda items: bool(set(items) & set(spec.values)) if isinstance(items, list) else False
            )
        else:
            mask = df[spec.column].astype(str).isin(spec.values)
        return f"{mask.sum() / len(df) * 100:.1f}%" if len(df) else "0%"
    return None


def _kpi_cards(df: pd.DataFrame, specs: list[KpiSpec]) -> str:
    cards = []
    for spec in specs:
        value = _kpi_value(df, spec)
        if value is None:
            continue
        cards.append(
            f'<div class="kpi-card {spec.flag}"><div class="kpi-icon">{spec.icon}</div>'
            f'<div class="kpi-value">{value}</div><div class="kpi-label">{spec.label}</div></div>'
        )
    if not cards:
        return ""
    return f'<div class="kpi-row" style="grid-template-columns: repeat({len(cards)}, 1fr)">' + "".join(cards) + "</div>"


def _insights(df: pd.DataFrame, max_items: int = 4) -> str:
    items: list[str] = []
    try:
        if "company" in df.columns and df["company"].astype(bool).any():
            top = df["company"].value_counts()
            items.append(f"🏆 <strong>{top.index[0]}</strong> leads hiring with {top.values[0]} open positions")
        if "skills" in df.columns:
            skills = [s for items_ in df["skills"].dropna() if isinstance(items_, list) for s in items_]
            if skills:
                skill, count = Counter(skills).most_common(1)[0]
                items.append(f"🛠️ <strong>{skill}</strong> is the most in-demand skill ({count} jobs)")
        if "location_clean" in df.columns and len(df):
            loc = df["location_clean"].value_counts()
            items.append(f"📍 <strong>{loc.index[0]}</strong> dominates with {loc.values[0] / len(df) * 100:.0f}% of all jobs")
        if "working_type" in df.columns and len(df):
            office = (df["working_type"] == "At office").sum() / len(df) * 100
            items.append(f"🏢 {office:.0f}% of jobs require office presence — remote work is still rare")
        elif "seniority" in df.columns and len(df):
            senior = df["seniority"].isin(SENIOR_PLUS).sum() / len(df) * 100
            items.append(f"🎯 {senior:.0f}% of jobs target senior candidates and above")
    except Exception:  # noqa: BLE001
        logger.exception("Không dựng được insights — bỏ qua")
    if not items:
        return ""
    body = "".join(f'<div class="insight-item">{i}</div>' for i in items[:max_items])
    return f'<div class="insights-panel"><div class="insights-title">💡 Key Insights</div>{body}</div>'


# ─── RENDER ──────────────────────────────────────────────────────────────────

_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{page_title}</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg: #0a0a1a; --card: rgba(255,255,255,0.04); --card-border: rgba(255,255,255,0.08);
    --accent1: #6C63FF; --accent2: #00D2FF; --accent3: #FF6B9D; --accent4: #C9F65D;
    --text: #E8E8F0; --text-dim: #7A7A8E;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: 'Inter', system-ui, -apple-system, sans-serif; background: var(--bg);
    color: var(--text); min-height: 100vh; overflow-x: hidden; }}
  body::before {{
    content: ''; position: fixed; top: -50%; left: -50%; width: 200%; height: 200%;
    background: radial-gradient(ellipse at 20% 50%, rgba(108,99,255,0.08) 0%, transparent 50%),
                radial-gradient(ellipse at 80% 20%, rgba(0,210,255,0.06) 0%, transparent 50%),
                radial-gradient(ellipse at 60% 80%, rgba(255,107,157,0.05) 0%, transparent 50%);
    animation: bgPulse 20s ease-in-out infinite alternate; z-index: -1;
  }}
  @keyframes bgPulse {{ 0% {{ transform: translate(0,0) scale(1); }} 100% {{ transform: translate(-5%,-3%) scale(1.05); }} }}
  .container {{ max-width: 1440px; margin: 0 auto; padding: 30px 24px; }}
  .header {{ text-align: center; margin-bottom: 40px; }}
  .header h1 {{
    font-size: 2.8rem; font-weight: 800; letter-spacing: -1px; margin-bottom: 8px;
    background: linear-gradient(135deg, #6C63FF 0%, #00D2FF 40%, #FF6B9D 70%, #C9F65D 100%);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
    animation: gradientShift 8s ease-in-out infinite; background-size: 200% 200%;
  }}
  @keyframes gradientShift {{ 0%,100% {{ background-position: 0% 50%; }} 50% {{ background-position: 100% 50%; }} }}
  .header .subtitle {{ color: var(--text-dim); font-size: 1rem; letter-spacing: 0.3px; }}
  .header .subtitle strong {{ color: var(--accent2); font-weight: 600; }}
  .kpi-row {{ display: grid; gap: 16px; margin-bottom: 20px; }}
  .kpi-card {{
    background: var(--card); backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px);
    border: 1px solid var(--card-border); border-radius: 16px; padding: 20px; text-align: center;
    transition: all 0.3s cubic-bezier(0.4,0,0.2,1); position: relative; overflow: hidden;
  }}
  .kpi-card::before {{ content: ''; position: absolute; top: 0; left: 0; right: 0; height: 2px;
    background: var(--accent1); opacity: 0; transition: opacity 0.3s; }}
  .kpi-card:hover {{ transform: translateY(-4px); border-color: rgba(108,99,255,0.3);
    box-shadow: 0 8px 32px rgba(108,99,255,0.15); }}
  .kpi-card:hover::before {{ opacity: 1; }}
  .kpi-card.hot {{ border-color: rgba(255,107,157,0.3); }}
  .kpi-card.hot::before {{ background: var(--accent3); }}
  .kpi-icon {{ font-size: 1.5rem; margin-bottom: 8px; }}
  .kpi-value {{ font-size: 2rem; font-weight: 800;
    background: linear-gradient(135deg, var(--accent1), var(--accent2));
    -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; }}
  .kpi-card.hot .kpi-value {{ background: linear-gradient(135deg, var(--accent3), #FF9F43);
    -webkit-background-clip: text; background-clip: text; }}
  .kpi-label {{ font-size: 0.8rem; color: var(--text-dim); margin-top: 4px;
    text-transform: uppercase; letter-spacing: 0.5px; font-weight: 500; }}
  .insights-panel {{ background: var(--card); backdrop-filter: blur(20px);
    border: 1px solid var(--card-border); border-radius: 16px; padding: 20px 28px;
    margin-bottom: 32px; position: relative; overflow: hidden; }}
  .insights-panel::before {{ content: ''; position: absolute; top: 0; left: 0; right: 0; height: 2px;
    background: linear-gradient(90deg, var(--accent1), var(--accent2), var(--accent3)); }}
  .insights-title {{ font-size: 1rem; font-weight: 700; color: var(--accent2); margin-bottom: 12px;
    text-transform: uppercase; letter-spacing: 0.5px; }}
  .insight-item {{ padding: 6px 0; font-size: 0.92rem; line-height: 1.6;
    border-bottom: 1px solid rgba(255,255,255,0.03); }}
  .insight-item:last-child {{ border-bottom: none; }}
  .insight-item strong {{ color: var(--accent2); font-weight: 600; }}
  .section-title {{ font-size: 1.1rem; font-weight: 700; color: var(--accent1);
    text-transform: uppercase; letter-spacing: 1px; margin: 36px 0 18px;
    padding-left: 16px; border-left: 3px solid var(--accent1); }}
  .grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 20px; }}
  .chart-card {{ background: var(--card); backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px);
    border: 1px solid var(--card-border); border-radius: 16px; padding: 20px; overflow: hidden;
    transition: all 0.3s ease; }}
  .chart-card:hover {{ border-color: rgba(108,99,255,0.2); box-shadow: 0 4px 20px rgba(108,99,255,0.08); }}
  .chart-card.full {{ grid-column: 1 / -1; }}
  .footer {{ text-align: center; color: var(--text-dim); margin-top: 48px; padding: 24px;
    font-size: 0.8rem; border-top: 1px solid var(--card-border); }}
  .footer a {{ color: var(--accent2); text-decoration: none; }}
  .kpi-card, .chart-card, .insights-panel {{ animation: fadeUp 0.6s ease-out both; }}
  @keyframes fadeUp {{ from {{ opacity: 0; transform: translateY(20px); }} to {{ opacity: 1; transform: translateY(0); }} }}
  .chart-card:nth-child(odd) {{ animation-delay: 0.1s; }}
  .chart-card:nth-child(even) {{ animation-delay: 0.2s; }}
  @media (max-width: 1200px) {{ .kpi-row {{ grid-template-columns: repeat(3, 1fr) !important; }} }}
  @media (max-width: 900px) {{
    .grid {{ grid-template-columns: 1fr; }}
    .kpi-row {{ grid-template-columns: repeat(2, 1fr) !important; }}
    .header h1 {{ font-size: 2rem; }}
  }}
  @media (max-width: 600px) {{ .kpi-row {{ grid-template-columns: 1fr !important; }} .container {{ padding: 16px 12px; }} }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>{heading}</h1>
    <p class="subtitle">{subtitle}</p>
  </div>
  {kpi}
  {insights}
  {sections}
  <div class="footer">{footer}</div>
</div>
</body>
</html>"""


def render_dashboard(
    *,
    df: pd.DataFrame,
    out_path: Path,
    heading: str,
    page_title: str,
    sections: list[Section],
    kpis: list[KpiSpec],
    data_url: str,
    data_label: str,
    source_label: str,
) -> Path:
    """Render dashboard HTML từ spec. Trả về đường dẫn file."""
    rendered_sections = []
    for section in sections:
        cards = []
        for spec in section.charts:
            html = build_chart(df, spec)
            if html:
                cards.append(f'<div class="chart-card{" full" if spec.full else ""}">{html}</div>')
        if cards:
            rendered_sections.append(
                f'<div class="section-title">{section.title}</div><div class="grid">{"".join(cards)}</div>'
            )

    if not rendered_sections:
        rendered_sections.append(
            '<div class="insights-panel"><div class="insight-item">'
            "Không có chart nào dựng được — kiểm tra lại processed CSV.</div></div>"
        )

    companies = df["company"].nunique() if "company" in df.columns else 0
    cities = df["location_clean"].nunique() if "location_clean" in df.columns else 0
    scrape_date = str(df["scraped_at"].iloc[0])[:10] if "scraped_at" in df.columns and len(df) else "N/A"

    html = _TEMPLATE.format(
        page_title=page_title,
        heading=heading,
        subtitle=(
            f'Real-time analysis of <strong>{len(df)}</strong> job listings &bull; '
            f"<strong>{companies}</strong> companies &bull; <strong>{cities}</strong> cities &bull; "
            f"Scraped <strong>{scrape_date}</strong>"
        ),
        kpi=_kpi_cards(df, kpis),
        insights=_insights(df),
        sections="".join(rendered_sections),
        footer=(
            f"Built with ❤️ by {source_label} Pipeline &bull; "
            f'Data: <a href="{data_url}" target="_blank">{data_label}</a> &bull; '
            f"{len(df)} jobs &bull; {scrape_date}"
        ),
    )

    # Ghi atomic (rename) để overwrite được file do user khác tạo trên volume dùng chung
    return atomic_write_text(out_path, html)


#: KPI chung cho mọi source (tự bỏ qua nếu thiếu cột).
BASE_KPIS: tuple[KpiSpec, ...] = (
    KpiSpec("💼", "Total Jobs", "count"),
    KpiSpec("🏢", "Companies", "nunique", column="company"),
    KpiSpec("📍", "Cities", "nunique", column="location_clean"),
    KpiSpec("🛠️", "Skills", "nunique_list", column="skills"),
)


def standard_kpis(*extra: KpiSpec) -> list[KpiSpec]:
    """KPI chuẩn + KPI riêng của source."""
    return [*BASE_KPIS, *extra]
