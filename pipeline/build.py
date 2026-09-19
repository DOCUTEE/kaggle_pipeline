#!/usr/bin/env python3
"""Centralized build orchestrator for the kaggle_pipeline project.

Gọi chung qua pipeline/runner.py (Airflow DAG jobs_daily là scheduler duy nhất).

Usage:
    python -m pipeline.build process itviec --data-dir data/itviec_v4
    python -m pipeline.build load-db itviec --data-dir data/itviec_v4
    python -m pipeline.build all itviec --data-dir data/itviec_v4 --load-db

Subcommands:
    process     Clean raw JSON → processed CSV
    dashboard   Build HTML dashboard from processed CSV
    load-db     Load processed CSV into PostgreSQL (for Grafana)
    all         process + load-db + optional kaggle push
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from itertools import combinations
from pathlib import Path

import pandas as pd

# ─── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        prog="pipeline build",
        description="Centralized build for iTViec / TopCV pipelines",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ── process ──
    p_proc = sub.add_parser("process", help="Clean raw JSON → processed CSV")
    p_proc.add_argument("source", choices=["itviec", "topcv", "arxiv"], help="Data source")
    p_proc.add_argument("--data-dir", type=Path, default=None, help="Data directory")
    p_proc.add_argument("--dashboard-dir", type=Path, default=None,
                        help="Dashboard output dir (default: <data-dir>/dashboard)")

    # ── dashboard ──
    p_dash = sub.add_parser("dashboard", help="Build HTML dashboard from processed CSV")
    p_dash.add_argument("source", choices=["itviec", "topcv", "arxiv"], help="Data source")
    p_dash.add_argument("--data-dir", type=Path, default=None, help="Data directory")
    p_dash.add_argument("--dashboard-dir", type=Path, default=None,
                        help="Dashboard output dir (default: <data-dir>/dashboard)")

    # ── load-db ──
    p_db = sub.add_parser("load-db", help="Load processed CSV into PostgreSQL")
    p_db.add_argument("source", choices=["itviec", "topcv", "arxiv"], help="Data source")
    p_db.add_argument("--csv", type=Path, help="Path to CSV file")
    p_db.add_argument("--data-dir", type=Path, default=None, help="Data directory")

    # ── all ──
    p_all = sub.add_parser("all", help="process + load-db (+ optional kaggle push)")
    p_all.add_argument("source", choices=["itviec", "topcv", "arxiv"], help="Data source")
    p_all.add_argument("--data-dir", type=Path, default=None, help="Data directory")
    p_all.add_argument("--dashboard-dir", type=Path, default=None,
                        help="Dashboard output dir (default: <data-dir>/dashboard)")
    p_all.add_argument("--push-kaggle", action="store_true", help="Push to Kaggle after build")
    p_all.add_argument("--kaggle-dataset", type=str, default=None, help="Kaggle dataset id")
    p_all.add_argument("--load-db", action="store_true", help="Load data into PostgreSQL after process")
    p_all.add_argument("--skip-kaggle", action="store_true", help="Skip Kaggle push")

    args = parser.parse_args()

    # Resolve paths
    project_root = Path(__file__).resolve().parent.parent
    source = args.source
    data_dir = args.data_dir or (project_root / "data" / source)
    dashboard_dir = args.dashboard_dir or (data_dir / "dashboard")
    dashboard_dir.mkdir(parents=True, exist_ok=True)

    print(f"{'=' * 60}")
    print(f"  Pipeline Build — {source.upper()}")
    print(f"  Data dir:     {data_dir}")
    print(f"  Dashboard dir: {dashboard_dir}")
    print(f"{'=' * 60}")

    if args.command == "process":
        if source == "itviec":
            process_itviec(data_dir, dashboard_dir)
        elif source == "arxiv":
            process_arxiv(data_dir, dashboard_dir)
        else:
            process_topcv(data_dir, dashboard_dir)

    elif args.command == "dashboard":
        if source == "itviec":
            build_itviec_dashboard(data_dir, dashboard_dir)
        elif source == "arxiv":
            build_arxiv_dashboard(data_dir, dashboard_dir)
        else:
            build_topcv_dashboard(data_dir, dashboard_dir)

    elif args.command == "load-db":
        from pipeline.db import load_arxiv_csv, load_itviec_csv, load_topcv_csv
        csv_path = args.csv
        if not csv_path:
            if source == "itviec":
                csv_path = dashboard_dir / "processed_jobs.csv"
            elif source == "arxiv":
                csv_path = dashboard_dir / "processed_arxiv.csv"
            else:
                csv_path = dashboard_dir / "processed_topcv.csv"
        if not csv_path.exists():
            print(f"[ERROR] CSV not found: {csv_path}")
            print("  Run 'process' first or provide --csv")
            sys.exit(1)
        if source == "itviec":
            load_itviec_csv(csv_path)
        elif source == "arxiv":
            load_arxiv_csv(csv_path)
        else:
            load_topcv_csv(csv_path)

    elif args.command == "all":
        # Process
        if source == "itviec":
            process_itviec(data_dir, dashboard_dir)
        elif source == "arxiv":
            process_arxiv(data_dir, dashboard_dir)
        else:
            process_topcv(data_dir, dashboard_dir)

        # Load to DB
        if getattr(args, "load_db", False):
            from pipeline.db import load_arxiv_csv, load_itviec_csv, load_topcv_csv
            if source == "itviec":
                csv_path = dashboard_dir / "processed_jobs.csv"
                if csv_path.exists():
                    load_itviec_csv(csv_path)
            elif source == "arxiv":
                csv_path = dashboard_dir / "processed_arxiv.csv"
                if csv_path.exists():
                    load_arxiv_csv(csv_path)
            else:
                csv_path = dashboard_dir / "processed_topcv.csv"
                if csv_path.exists():
                    load_topcv_csv(csv_path)

        # Kaggle push
        if getattr(args, "push_kaggle", False) and not getattr(args, "skip_kaggle", False):
            kaggle_id = args.kaggle_dataset or _default_kaggle_id(source)
            push_to_kaggle(dashboard_dir, kaggle_id)


# ══════════════════════════════════════════════════════════════════════════════
#  ITVIEC
# ══════════════════════════════════════════════════════════════════════════════

# ─── SKILL TAXONOMY ──────────────────────────────────────────────────────────

SKILL_CATEGORIES: dict[str, set[str]] = {
    "Languages": {
        "Python", "Java", "JavaScript", "TypeScript", "C#", "C++", "Go", "Golang",
        "Rust", "Kotlin", "Swift", "Ruby", "PHP", "Scala", "Dart", "R", "SQL",
        "HTML", "CSS", "Shell Scripting", "Bash", "PowerShell",
    },
    "Frontend": {
        "React", "ReactJS", "Vue", "VueJS", "Angular", "AngularJS", "NextJS",
        "Next.js", "Svelte", "HTML", "CSS", "SASS", "Tailwind CSS", "Bootstrap",
        "jQuery", "Webpack", "Vite", "NuxtJS",
    },
    "Backend": {
        "NodeJS", "Node.js", "ExpressJS", "Django", "Flask", "FastAPI", "Spring Boot",
        "Spring", "ASP.NET", ".NET", "Laravel", "Ruby on Rails", "NestJS",
        "Microservices", "REST API", "GraphQL", "gRPC",
    },
    "Database": {
        "SQL", "MySQL", "PostgreSQL", "PostgreSql", "MongoDB", "Redis", "Elasticsearch",
        "DynamoDB", "Cassandra", "Oracle", "SQL Server", "MariaDB", "SQLite",
        "Neo4j", "InfluxDB", "Firestore", "Supabase",
    },
    "Cloud & DevOps": {
        "AWS", "Azure", "GCP", "Google Cloud", "Docker", "Kubernetes", "K8s",
        "Jenkins", "CI/CD", "Terraform", "Ansible", "Cloud", "DevOps",
        "GitHub Actions", "GitLab CI", "Prometheus", "Grafana", "Linux",
        "Nginx", "Apache", "Microservices",
    },
    "Data & AI": {
        "Machine Learning", "ML", "Deep Learning", "AI", "Data Science",
        "Data Engineer", "Data Analysis", "Data Analytics", "ETL", "Spark",
        "Hadoop", "Kafka", "Airflow", "TensorFlow", "PyTorch", "NLP",
        "Computer Vision", "LLM", "Generative AI", "GenAI", "Power BI",
        "Tableau", "dbt",
    },
    "Mobile": {
        "iOS", "Android", "React Native", "Flutter", "Swift", "Kotlin",
        "Dart", "Xamarin", "Ionic", "ReactNative",
    },
    "Testing": {
        "QA QC", "Automation Test", "Selenium", "Cypress", "Jest", "Tester",
        "ISTQB", "Manual Testing", "Performance Testing", "JMeter",
    },
    "Soft Skills & Process": {
        "Agile", "Scrum", "Kanban", "Project Management", "Team Management",
        "English", "Japanese", "Communication", "Leadership",
        "Business Analysis", "Stakeholder management", "Risk Management",
        "Technical Writing", "CI/CD",
    },
}

_SKILL_TO_CATEGORY: dict[str, str] = {}
for _cat, _skills in SKILL_CATEGORIES.items():
    for _s in _skills:
        _SKILL_TO_CATEGORY[_s.lower()] = _cat


def _extract_seniority(title: str, job_function: str) -> str:
    text = f"{title} {job_function}".lower()
    if any(w in text for w in ["intern", "internship"]):
        return "Intern"
    if any(w in text for w in ["fresher", "junior", "entry level"]):
        return "Fresher/Junior"
    if any(w in text for w in ["mid level", "mid-level"]):
        return "Mid-level"
    if any(w in text for w in ["senior", "sr.", "sr ", "lead", "principal"]):
        return "Senior/Lead"
    if any(w in text for w in ["manager", "director", "head", "vp", "cto"]):
        return "Manager+"
    if any(w in text for w in ["staff", "architect"]):
        return "Staff/Architect"
    m = re.search(r"(\d+)\+?\s*(?:yoe|years?)", text)
    if m:
        y = int(m.group(1))
        return "Fresher/Junior" if y <= 2 else ("Mid-level" if y <= 4 else "Senior/Lead")
    return "Not specified"


def _parse_posted_hours(posted: str) -> float | None:
    if not posted:
        return None
    m = re.search(r"(\d+)\s*(minute|hour|day|week|month)", posted.lower())
    if not m:
        return None
    val, unit = int(m.group(1)), m.group(2)
    if unit.startswith("minute"):
        return val / 60
    if unit.startswith("hour"):
        return float(val)
    if unit.startswith("day"):
        return val * 24
    if unit.startswith("week"):
        return val * 24 * 7
    if unit.startswith("month"):
        return val * 24 * 30
    return None


def _normalize_location(loc: str) -> str:
    loc = loc.strip()
    if not loc:
        return "Unknown"
    low = loc.lower()
    if "ho chi minh" in low and "ha noi" in low:
        return "HCM + Ha Noi"
    if "ho chi minh" in low:
        return "Ho Chi Minh"
    if "ha noi" in low:
        return "Ha Noi"
    if "da nang" in low:
        return "Da Nang"
    return loc


def process_itviec(data_dir: Path, out_dir: Path) -> Path:
    """Load raw JSON, clean, enrich, save processed CSV. Returns CSV path."""
    raw_json = data_dir / "itviec_jobs_latest.json"
    if not raw_json.exists():
        # Try alternative naming
        candidates = sorted(data_dir.glob("itviec_jobs_*.json"))
        if candidates:
            raw_json = candidates[-1]
        else:
            raise FileNotFoundError(f"No raw JSON found in {data_dir}")

    print(f"\n[process] Loading {raw_json}")
    with open(raw_json) as f:
        raw = json.load(f)
    jobs = raw["jobs"]
    df = pd.DataFrame(jobs)
    print(f"  → {len(df)} jobs loaded")

    # Clean
    df["salary"] = df["salary"].replace("Sign in to view salary", "")
    df["tags"] = df["tags"].apply(lambda x: x if isinstance(x, list) else [])
    df["highlights"] = df["highlights"].apply(lambda x: x if isinstance(x, list) else [])

    # Feature engineering
    df["seniority"] = df.apply(lambda r: _extract_seniority(r["title"], r["job_function"]), axis=1)
    df["posted_hours_ago"] = df["posted_time"].apply(_parse_posted_hours)

    def _assign_cats(tags):
        cats = set()
        for t in tags:
            c = _SKILL_TO_CATEGORY.get(t.lower())
            if c:
                cats.add(c)
        return sorted(cats)

    df["skill_categories"] = df["tags"].apply(_assign_cats)
    df["location_clean"] = df["location"].apply(_normalize_location)
    df["num_tags"] = df["tags"].apply(len)
    df["has_highlights"] = df["highlights"].apply(len) > 0
    df["label_clean"] = df["label"].fillna("").replace("", "None")

    csv_path = out_dir / "processed_jobs.csv"
    df.to_csv(csv_path, index=False)
    print(f"  → Saved {csv_path} ({len(df)} rows)")
    return csv_path


# ─── ITVIEC DASHBOARD (Plotly HTML) ──────────────────────────────────────────

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


def _plotly_template():
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


def _fig_html(fig) -> str:
    fig.update_layout(**_plotly_template()["layout"])
    return fig.to_html(full_html=False, include_plotlyjs=False)


def _load_dashboard_df(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    for col in ("tags", "skill_categories", "highlights"):
        if col in df.columns:
            df[col] = df[col].apply(lambda x: eval(x) if isinstance(x, str) else x)
    return df


def _kpi_cards(df: pd.DataFrame) -> str:
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
        html += f'<div class="kpi-card {extra}"><div class="kpi-icon">{icon}</div><div class="kpi-value">{value}</div><div class="kpi-label">{label}</div></div>'
    html += '</div>'
    return html


def _insights(df: pd.DataFrame) -> str:
    top_company = df["company"].value_counts().index[0]
    top_company_n = df["company"].value_counts().values[0]
    all_tags = [t for tags in df["tags"] if isinstance(tags, list) for t in tags]
    top_skill = Counter(all_tags).most_common(1)[0]
    top_loc = df["location_clean"].value_counts().index[0]
    top_loc_pct = df["location_clean"].value_counts().values[0] / len(df) * 100
    office_pct = len(df[df["working_type"] == "At office"]) / len(df) * 100

    items = [
        f"🏆 <strong>{top_company}</strong> leads hiring with {top_company_n} open positions",
        f"🛠️ <strong>{top_skill[0]}</strong> is the most in-demand skill ({top_skill[1]} jobs)",
        f"📍 <strong>{top_loc}</strong> dominates with {top_loc_pct:.0f}% of all jobs",
        f"🏢 {office_pct:.0f}% of jobs require office presence — remote work is still rare",
    ]
    html = '<div class="insights-panel"><div class="insights-title">💡 Key Insights</div>'
    for i in items:
        html += f'<div class="insight-item">{i}</div>'
    html += '</div>'
    return html


def _chart_location(df):
    import plotly.express as px
    c = df["location_clean"].value_counts()
    fig = px.bar(x=c.index, y=c.values, labels={"x": "", "y": "Jobs"}, title="📍 Jobs by Location",
                 color=c.index, color_discrete_map=LOCATION_COLORS, text=c.values)
    fig.update_layout(showlegend=False)
    fig.update_traces(textposition="outside", textfont_size=12, marker_line_width=0)
    return _fig_html(fig)


def _chart_wt_loc(df):
    import plotly.graph_objects as go
    cross = pd.crosstab(df["location_clean"], df["working_type"])
    fig = go.Figure()
    for i, col in enumerate(cross.columns):
        fig.add_trace(go.Bar(name=col, x=cross.index, y=cross[col],
                             marker_color=list(WORKING_COLORS.values())[i % 3], marker_line_width=0))
    fig.update_layout(barmode="stack", title="🏠 Working Type × Location",
                      xaxis_title="", yaxis_title="Jobs",
                      legend=dict(orientation="h", y=1.12, x=0.5, xanchor="center"))
    return _fig_html(fig)


def _chart_seniority(df):
    import plotly.express as px
    order = ["Intern", "Fresher/Junior", "Mid-level", "Not specified", "Senior/Lead", "Staff/Architect", "Manager+"]
    c = df["seniority"].value_counts().reindex([o for o in order if o in df["seniority"].value_counts().index]).dropna()
    fig = px.pie(names=c.index, values=c.values, title="🎯 Seniority Breakdown", hole=0.55,
                 color_discrete_sequence=CHART_COLORS)
    fig.update_traces(textposition="inside", textinfo="percent+label", textfont_size=11,
                      marker=dict(line=dict(color="rgba(10,10,26,0.8)", width=2)))
    fig.update_layout(legend=dict(font=dict(size=11)))
    return _fig_html(fig)


def _chart_wt(df):
    import plotly.express as px
    c = df["working_type"].value_counts()
    fig = px.pie(names=c.index, values=c.values, title="🏢 Work Mode", hole=0.55,
                 color=c.index, color_discrete_map=WORKING_COLORS)
    fig.update_traces(textposition="inside", textinfo="percent+label", textfont_size=12,
                      marker=dict(line=dict(color="rgba(10,10,26,0.8)", width=2)))
    return _fig_html(fig)


def _chart_top_skills(df):
    import plotly.graph_objects as go
    all_tags = [t for tags in df["tags"] if isinstance(tags, list) for t in tags]
    tc = Counter(all_tags).most_common(20)
    tags, counts = zip(*tc)
    colors = [CHART_COLORS[i % len(CHART_COLORS)] for i in range(len(tags))][::-1]
    fig = go.Figure(go.Bar(x=list(counts)[::-1], y=list(tags)[::-1], orientation="h",
                           marker=dict(color=colors, line_width=0),
                           text=list(counts)[::-1], textposition="outside", textfont=dict(size=11)))
    fig.update_layout(title="🛠️ Top 20 Skills in Demand", xaxis_title="Jobs", yaxis_title="", height=520)
    return _fig_html(fig)


def _chart_skill_cats(df):
    import plotly.graph_objects as go
    all_cats = [c for cats in df["skill_categories"] if isinstance(cats, list) for c in cats]
    cc = Counter(all_cats).most_common()
    fig = go.Figure(go.Bar(x=[c[0] for c in cc], y=[c[1] for c in cc],
                           marker=dict(color=[CHART_COLORS[i % len(CHART_COLORS)] for i in range(len(cc))], line_width=0),
                           text=[c[1] for c in cc], textposition="outside", textfont=dict(size=12)))
    fig.update_layout(title="📚 Skill Categories", xaxis_title="", yaxis_title="Jobs")
    return _fig_html(fig)


def _chart_top_companies(df):
    import plotly.graph_objects as go
    c = df["company"].value_counts().head(15)
    fig = go.Figure(go.Bar(x=c.index, y=c.values,
                           marker=dict(color=c.values, colorscale=[[0, "#6C63FF"], [0.5, "#00D2FF"], [1, "#C9F65D"]], line_width=0),
                           text=c.values, textposition="outside", textfont=dict(size=11)))
    fig.update_layout(title="🏢 Top 15 Hiring Companies", xaxis_title="", yaxis_title="Jobs", xaxis_tickangle=-35)
    return _fig_html(fig)


def _chart_label(df):
    import plotly.express as px
    c = df["label_clean"].value_counts()
    fig = px.pie(names=c.index, values=c.values, title="🔥 Job Urgency Labels", hole=0.5,
                 color=c.index, color_discrete_map=LABEL_COLORS)
    fig.update_traces(textposition="inside", textinfo="percent+label",
                      marker=dict(line=dict(color="rgba(10,10,26,0.8)", width=2)))
    return _fig_html(fig)


def _chart_freshness(df):
    import plotly.express as px
    v = df["posted_hours_ago"].dropna()
    v = v[v < 500]
    fig = px.histogram(x=v, nbins=35, labels={"x": "Hours Ago", "y": "Jobs"},
                       title="⏰ Job Freshness", color_discrete_sequence=["#6C63FF"])
    fig.update_traces(marker_line_width=0, marker_line_color="rgba(0,0,0,0)")
    return _fig_html(fig)


def _chart_sr_loc(df):
    import plotly.graph_objects as go
    order = ["Intern", "Fresher/Junior", "Mid-level", "Not specified", "Senior/Lead", "Staff/Architect", "Manager+"]
    cross = pd.crosstab(df["location_clean"], df["seniority"])
    cross = cross[[c for c in order if c in cross.columns]]
    fig = go.Figure()
    for i, col in enumerate(cross.columns):
        fig.add_trace(go.Bar(name=col, x=cross.index, y=cross[col],
                             marker_color=CHART_COLORS[i % len(CHART_COLORS)], marker_line_width=0))
    fig.update_layout(barmode="stack", title="📊 Seniority × Location", xaxis_title="", yaxis_title="Jobs",
                      legend=dict(orientation="h", y=1.15, x=0.5, xanchor="center", font=dict(size=11)))
    return _fig_html(fig)


def _chart_heatmap(df):
    import plotly.express as px
    rows = [{"seniority": r["seniority"], "skill": t}
            for _, r in df.iterrows() if isinstance(r["tags"], list) for t in r["tags"]]
    edf = pd.DataFrame(rows)
    top = edf["skill"].value_counts().head(15).index.tolist()
    filt = edf[edf["skill"].isin(top)]
    pivot = pd.crosstab(filt["skill"], filt["seniority"])
    order = ["Intern", "Fresher/Junior", "Mid-level", "Not specified", "Senior/Lead", "Staff/Architect", "Manager+"]
    pivot = pivot[[c for c in order if c in pivot.columns]].loc[top]
    fig = px.imshow(pivot, title="🗺️ Skills × Seniority Heatmap",
                    labels=dict(x="", y="", color="Jobs"),
                    color_continuous_scale=[[0, "#0a0a1a"], [0.2, "#6C63FF"], [0.6, "#00D2FF"], [1, "#C9F65D"]],
                    aspect="auto")
    fig.update_layout(coloraxis_showscale=False)
    return _fig_html(fig)


def _chart_cooccurrence(df):
    import plotly.express as px
    pair_c = Counter()
    for tags in df["tags"]:
        if isinstance(tags, list) and len(tags) >= 2:
            for a, b in combinations(sorted(set(tags)), 2):
                pair_c[(a, b)] += 1
    top_pairs = pair_c.most_common(12)
    all_s = {s for (a, b), _ in top_pairs for s in (a, b)}
    skills = sorted(all_s)[:12]
    matrix = pd.DataFrame(0, index=skills, columns=skills)
    for (a, b), cnt in pair_c.items():
        if a in skills and b in skills:
            matrix.loc[a, b] = cnt
            matrix.loc[b, a] = cnt
    fig = px.imshow(matrix, title="🔗 Skill Co-occurrence",
                    labels=dict(x="", y="", color="Pairs"),
                    color_continuous_scale=[[0, "#0a0a1a"], [0.3, "#6C63FF"], [1, "#00D2FF"]], aspect="auto")
    fig.update_layout(coloraxis_showscale=False)
    return _fig_html(fig)


def build_itviec_dashboard(data_dir: Path, out_dir: Path) -> Path:
    """Build iTViec HTML dashboard. Returns HTML path."""
    csv_path = out_dir / "processed_jobs.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"Run 'process' first — no {csv_path}")

    print(f"\n[dashboard] Building iTViec dashboard from {csv_path}")
    df = _load_dashboard_df(csv_path)

    kpi = _kpi_cards(df)
    ins = _insights(df)
    charts = [
        _chart_location(df), _chart_wt_loc(df), _chart_seniority(df), _chart_wt(df),
        _chart_label(df), _chart_freshness(df), _chart_top_skills(df), _chart_skill_cats(df),
        _chart_cooccurrence(df), _chart_top_companies(df), _chart_sr_loc(df), _chart_heatmap(df),
    ]

    scrape_date = df["scraped_at"].iloc[0][:10] if "scraped_at" in df.columns else "N/A"

    html = _ITVIEC_DASHBOARD_HTML.format(
        n_jobs=len(df), n_companies=df["company"].nunique(),
        n_cities=df["location_clean"].nunique(), scrape_date=scrape_date,
        kpi=kpi, insights=ins,
        c1=charts[0], c2=charts[1], c3=charts[2], c4=charts[3],
        c5=charts[4], c6=charts[5], c7=charts[6], c8=charts[7],
        c9=charts[8], c10=charts[9], c11=charts[10], c12=charts[11],
    )

    out_html = out_dir / "itviec_dashboard.html"
    out_html.write_text(html, encoding="utf-8")
    print(f"  → Dashboard saved: {out_html}")
    print(f"  → Open: file://{out_html.resolve()}")
    return out_html


# ─── HTML TEMPLATE ────────────────────────────────────────────────────────────

_ITVIEC_DASHBOARD_HTML = '''<!DOCTYPE html>
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
    background: var(--bg); color: var(--text); min-height: 100vh; overflow-x: hidden;
  }}
  body::before {{
    content: ''; position: fixed; top: -50%; left: -50%; width: 200%; height: 200%;
    background: radial-gradient(ellipse at 20% 50%, rgba(108,99,255,0.08) 0%, transparent 50%),
                radial-gradient(ellipse at 80% 20%, rgba(0,210,255,0.06) 0%, transparent 50%),
                radial-gradient(ellipse at 60% 80%, rgba(255,107,157,0.05) 0%, transparent 50%);
    animation: bgPulse 20s ease-in-out infinite alternate; z-index: -1;
  }}
  @keyframes bgPulse {{
    0% {{ transform: translate(0, 0) scale(1); }}
    100% {{ transform: translate(-5%, -3%) scale(1.05); }}
  }}
  .container {{ max-width: 1440px; margin: 0 auto; padding: 30px 24px; }}
  .header {{ text-align: center; margin-bottom: 40px; }}
  .header h1 {{
    font-size: 2.8rem; font-weight: 800; letter-spacing: -1px; margin-bottom: 8px;
    background: linear-gradient(135deg, #6C63FF 0%, #00D2FF 40%, #FF6B9D 70%, #C9F65D 100%);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
    animation: gradientShift 8s ease-in-out infinite; background-size: 200% 200%;
  }}
  @keyframes gradientShift {{
    0%, 100% {{ background-position: 0% 50%; }}
    50% {{ background-position: 100% 50%; }}
  }}
  .header .subtitle {{ color: var(--text-dim); font-size: 1rem; font-weight: 400; letter-spacing: 0.3px; }}
  .header .subtitle strong {{ color: var(--accent2); font-weight: 600; }}
  .kpi-row {{ display: grid; grid-template-columns: repeat(6, 1fr); gap: 16px; margin-bottom: 20px; }}
  .kpi-card {{
    background: var(--card); backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px);
    border: 1px solid var(--card-border); border-radius: 16px; padding: 20px;
    text-align: center; transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    position: relative; overflow: hidden;
  }}
  .kpi-card::before {{
    content: ''; position: absolute; top: 0; left: 0; right: 0; height: 2px;
    background: var(--accent1); opacity: 0; transition: opacity 0.3s;
  }}
  .kpi-card:hover {{
    transform: translateY(-4px); border-color: rgba(108,99,255,0.3);
    box-shadow: 0 8px 32px rgba(108,99,255,0.15);
  }}
  .kpi-card:hover::before {{ opacity: 1; }}
  .kpi-card.hot {{ border-color: rgba(255,107,157,0.3); }}
  .kpi-card.hot::before {{ background: var(--accent3); }}
  .kpi-card.hot:hover {{ box-shadow: 0 8px 32px rgba(255,107,157,0.15); }}
  .kpi-icon {{ font-size: 1.5rem; margin-bottom: 8px; }}
  .kpi-value {{
    font-size: 2rem; font-weight: 800;
    background: linear-gradient(135deg, var(--accent1), var(--accent2));
    -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
  }}
  .kpi-card.hot .kpi-value {{
    background: linear-gradient(135deg, var(--accent3), #FF9F43);
    -webkit-background-clip: text; background-clip: text;
  }}
  .kpi-label {{
    font-size: 0.8rem; color: var(--text-dim); margin-top: 4px;
    text-transform: uppercase; letter-spacing: 0.5px; font-weight: 500;
  }}
  .insights-panel {{
    background: var(--card); backdrop-filter: blur(20px);
    border: 1px solid var(--card-border); border-radius: 16px;
    padding: 20px 28px; margin-bottom: 32px; position: relative; overflow: hidden;
  }}
  .insights-panel::before {{
    content: ''; position: absolute; top: 0; left: 0; right: 0; height: 2px;
    background: linear-gradient(90deg, var(--accent1), var(--accent2), var(--accent3));
  }}
  .insights-title {{
    font-size: 1rem; font-weight: 700; color: var(--accent2);
    margin-bottom: 12px; text-transform: uppercase; letter-spacing: 0.5px;
  }}
  .insight-item {{
    padding: 6px 0; font-size: 0.92rem; color: var(--text); line-height: 1.6;
    border-bottom: 1px solid rgba(255,255,255,0.03);
  }}
  .insight-item:last-child {{ border-bottom: none; }}
  .insight-item strong {{ color: var(--accent2); font-weight: 600; }}
  .section-title {{
    font-size: 1.1rem; font-weight: 700; color: var(--accent1);
    text-transform: uppercase; letter-spacing: 1px; margin: 36px 0 18px;
    padding-left: 16px; border-left: 3px solid var(--accent1);
  }}
  .grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 20px; }}
  .chart-card {{
    background: var(--card); backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px);
    border: 1px solid var(--card-border); border-radius: 16px;
    padding: 20px; overflow: hidden; transition: all 0.3s ease;
  }}
  .chart-card:hover {{
    border-color: rgba(108,99,255,0.2); box-shadow: 0 4px 20px rgba(108,99,255,0.08);
  }}
  .chart-card.full {{ grid-column: 1 / -1; }}
  .footer {{
    text-align: center; color: var(--text-dim); margin-top: 48px;
    padding: 24px; font-size: 0.8rem; border-top: 1px solid var(--card-border);
  }}
  .footer a {{ color: var(--accent2); text-decoration: none; }}
  .kpi-card, .chart-card, .insights-panel {{ animation: fadeUp 0.6s ease-out both; }}
  @keyframes fadeUp {{
    from {{ opacity: 0; transform: translateY(20px); }}
    to {{ opacity: 1; transform: translateY(0); }}
  }}
  .kpi-card:nth-child(1) {{ animation-delay: 0.05s; }}
  .kpi-card:nth-child(2) {{ animation-delay: 0.1s; }}
  .kpi-card:nth-child(3) {{ animation-delay: 0.15s; }}
  .kpi-card:nth-child(4) {{ animation-delay: 0.2s; }}
  .kpi-card:nth-child(5) {{ animation-delay: 0.25s; }}
  .kpi-card:nth-child(6) {{ animation-delay: 0.3s; }}
  .chart-card:nth-child(odd) {{ animation-delay: 0.1s; }}
  .chart-card:nth-child(even) {{ animation-delay: 0.2s; }}
  @media (max-width: 1200px) {{ .kpi-row {{ grid-template-columns: repeat(3, 1fr); }} }}
  @media (max-width: 900px) {{
    .grid {{ grid-template-columns: 1fr; }}
    .kpi-row {{ grid-template-columns: repeat(2, 1fr); }}
    .header h1 {{ font-size: 2rem; }}
  }}
  @media (max-width: 600px) {{ .kpi-row {{ grid-template-columns: 1fr; }} .container {{ padding: 16px 12px; }} }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>🇻🇳 ITviec Job Market</h1>
    <p class="subtitle">
      Real-time analysis of <strong>{n_jobs}</strong> IT job listings &bull;
      <strong>{n_companies}</strong> companies &bull;
      <strong>{n_cities}</strong> cities &bull;
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
    <div class="chart-card">{c5}</div>
    <div class="chart-card">{c6}</div>
  </div>
  <div class="section-title">🛠️ Skills & Technologies</div>
  <div class="grid">
    <div class="chart-card full">{c7}</div>
    <div class="chart-card">{c8}</div>
    <div class="chart-card">{c9}</div>
  </div>
  <div class="section-title">🏢 Companies & Cross-analysis</div>
  <div class="grid">
    <div class="chart-card">{c10}</div>
    <div class="chart-card">{c11}</div>
    <div class="chart-card full">{c12}</div>
  </div>
  <div class="footer">
    Built with ❤️ by ITviec Pipeline &bull;
    Data: <a href="https://itviec.com" target="_blank">itviec.com</a> &bull;
    {n_jobs} jobs &bull; {scrape_date}
  </div>
</div>
</body>
</html>'''


# ══════════════════════════════════════════════════════════════════════════════
#  TOPCV
# ══════════════════════════════════════════════════════════════════════════════

def process_topcv(data_dir: Path, out_dir: Path) -> Path:
    """Load TopCV raw CSV, clean, save processed CSV."""
    latest = data_dir / "topcv_jobs_latest.csv"
    if not latest.exists():
        candidates = sorted(data_dir.glob("topcv_jobs_*.csv"))
        if candidates:
            latest = candidates[-1]
        else:
            raise FileNotFoundError(f"No TopCV CSV found in {data_dir}")

    print(f"\n[process] Loading {latest}")
    df = pd.read_csv(latest)
    print(f"  → {len(df)} jobs loaded")

    # Basic cleaning
    if "salary" in df.columns:
        df["salary"] = df["salary"].fillna("Thỏa thuận")
    if "title" in df.columns:
        df = df[df["title"].str.strip().astype(bool)]

    csv_path = out_dir / "processed_topcv.csv"
    df.to_csv(csv_path, index=False)
    print(f"  → Saved {csv_path} ({len(df)} rows)")
    return csv_path


def build_topcv_dashboard(data_dir: Path, out_dir: Path) -> Path:
    """Build TopCV HTML dashboard (simple version for now)."""
    csv_path = out_dir / "processed_topcv.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"Run 'process' first — no {csv_path}")

    print(f"\n[dashboard] Building TopCV dashboard from {csv_path}")
    df = pd.read_csv(csv_path)

    import plotly.express as px
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    charts_html = []

    # Location chart
    if "location" in df.columns:
        c = df["location"].value_counts().head(10)
        fig = px.bar(x=c.values, y=c.index, orientation="h", title="📍 Jobs by Location",
                     color=c.values, color_continuous_scale="viridis")
        fig.update_layout(height=400, showlegend=False)
        charts_html.append(("📍 Location", fig.to_html(full_html=False, include_plotlyjs=False)))

    # Company chart
    if "company" in df.columns:
        c = df["company"].value_counts().head(10)
        fig = px.pie(values=c.values, names=c.index, hole=0.3, title="🏢 Top Companies")
        fig.update_layout(height=400)
        charts_html.append(("🏢 Companies", fig.to_html(full_html=False, include_plotlyjs=False)))

    # Salary chart
    if "salary" in df.columns:
        sal = df[df["salary"] != "Thỏa thuận"]["salary"].value_counts().head(10)
        if not sal.empty:
            fig = px.bar(x=sal.index, y=sal.values, title="💰 Salary Distribution",
                         color=sal.values, color_continuous_scale="blues")
            fig.update_layout(height=400, xaxis_tickangle=45)
            charts_html.append(("💰 Salary", fig.to_html(full_html=False, include_plotlyjs=False)))

    # Skills chart
    if "skills" in df.columns:
        all_skills = []
        for s in df["skills"].dropna():
            if isinstance(s, str):
                all_skills.extend([x.strip() for x in s.split("|") if x.strip()])
        if all_skills:
            sc = pd.Series(all_skills).value_counts().head(15)
            fig = px.bar(x=sc.index, y=sc.values, title="🛠️ Top Skills",
                         color=sc.values, color_continuous_scale="teal")
            fig.update_layout(height=400, xaxis_tickangle=45)
            charts_html.append(("🛠️ Skills", fig.to_html(full_html=False, include_plotlyjs=False)))

    # Build HTML
    charts_section = "\n".join(
        f'<div class="chart-card"><h3>{title}</h3>{html}</div>'
        for title, html in charts_html
    )

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>TopCV Job Market Dashboard</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
<style>
  :root {{ --bg: #0a0a1a; --card: rgba(255,255,255,0.04); --card-border: rgba(255,255,255,0.08);
    --accent1: #6C63FF; --accent2: #00D2FF; --text: #E8E8F0; --text-dim: #7A7A8E; }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: 'Inter', sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; }}
  .container {{ max-width: 1440px; margin: 0 auto; padding: 30px 24px; }}
  .header {{ text-align: center; margin-bottom: 40px; }}
  .header h1 {{
    font-size: 2.8rem; font-weight: 800;
    background: linear-gradient(135deg, #6C63FF, #00D2FF);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
  }}
  .kpi-row {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 32px; }}
  .kpi-card {{
    background: var(--card); border: 1px solid var(--card-border); border-radius: 16px;
    padding: 20px; text-align: center;
  }}
  .kpi-value {{ font-size: 2rem; font-weight: 800; color: var(--accent2); }}
  .kpi-label {{ font-size: 0.8rem; color: var(--text-dim); text-transform: uppercase; margin-top: 4px; }}
  .grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 20px; }}
  .chart-card {{
    background: var(--card); border: 1px solid var(--card-border); border-radius: 16px; padding: 20px;
  }}
  .chart-card h3 {{ color: var(--accent2); font-size: 1rem; margin-bottom: 12px; }}
  @media (max-width: 900px) {{ .grid {{ grid-template-columns: 1fr; }} .kpi-row {{ grid-template-columns: repeat(2, 1fr); }} }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>🇻🇳 TopCV IT Jobs Vietnam</h1>
    <p style="color: var(--text-dim);">{len(df)} jobs &bull; {df["company"].nunique() if "company" in df.columns else 0} companies</p>
  </div>
  <div class="kpi-row">
    <div class="kpi-card"><div class="kpi-value">{len(df)}</div><div class="kpi-label">Total Jobs</div></div>
    <div class="kpi-card"><div class="kpi-value">{df["company"].nunique() if "company" in df.columns else 0}</div><div class="kpi-label">Companies</div></div>
    <div class="kpi-card"><div class="kpi-value">{df["location"].nunique() if "location" in df.columns else 0}</div><div class="kpi-label">Locations</div></div>
    <div class="kpi-card"><div class="kpi-value">{int(df["is_hot"].sum()) if "is_hot" in df.columns else 0}</div><div class="kpi-label">Hot Jobs</div></div>
  </div>
  <div class="grid">{charts_section}</div>
</div>
</body>
</html>'''

    out_html = out_dir / "topcv_dashboard.html"
    out_html.write_text(html, encoding="utf-8")
    print(f"  → Dashboard saved: {out_html}")
    return out_html


# ══════════════════════════════════════════════════════════════════════════════
#  ARXIV (papers + PDF -> MinIO, metadata -> Postgres)
# ══════════════════════════════════════════════════════════════════════════════

def process_arxiv(data_dir: Path, out_dir: Path) -> Path:
    """Chuẩn hóa metadata arXiv: latest CSV -> processed CSV (giữ nguyên cột).

    Scraper đã ghi arxiv_latest.csv đầy đủ cột cho Postgres/Kaggle,
    bước process chỉ copy + validate nhẹ để đúng pattern 6 bước chung.
    """
    latest = data_dir / "arxiv_latest.csv"
    if not latest.exists():
        candidates = sorted(data_dir.glob("arxiv_*.csv"))
        candidates = [c for c in candidates if "processed" not in c.name]
        if candidates:
            latest = candidates[-1]
        else:
            raise FileNotFoundError(f"No arXiv CSV found in {data_dir}")

    print(f"\n[process] Loading {latest}")
    df = pd.read_csv(latest)
    print(f"  → {len(df)} papers loaded")

    # Validate nhẹ: bỏ row thiếu arxiv_id/title
    if "title" in df.columns:
        df = df[df["title"].astype(str).str.strip().astype(bool)]
    if "arxiv_id" in df.columns:
        df = df.drop_duplicates(subset=["arxiv_id"], keep="last")

    csv_path = out_dir / "processed_arxiv.csv"
    df.to_csv(csv_path, index=False)
    print(f"  → Saved {csv_path} ({len(df)} rows)")
    return csv_path


def _arxiv_field(cat: str) -> str:
    """Gom primary_category arXiv thành nhóm lĩnh vực lớn."""
    c = (cat or "").strip()
    if c.startswith("cs."):
        return "Computer Science"
    if c.startswith("math"):
        return "Mathematics"
    if c.startswith("q-bio"):
        return "Quantitative Biology"
    if c.startswith("q-fin"):
        return "Quantitative Finance"
    if c == "stat" or c.startswith("stat."):
        return "Statistics"
    if c.startswith("eess"):
        return "EESS"
    if c.startswith("econ"):
        return "Economics"
    return "Physics"


_ARXIV_STOPWORDS = frozenset(
    "a an the and or of to in on for with by from as at is are was were be been being "
    "this that these those it its into over under between through during via per "
    "we our they their he she his her you your i "
    "paper papers study studies result results method methods approach approaches "
    "novel new using use used based propose proposed present presents "
    "model models system systems framework frameworks "
    "analysis analyze analysed theoretical experimental review overview "
    "towards toward within without high low large small first second "
    "can may also well one two more most many much such than then thus however "
    "upon et al".split()
)


def _arxiv_top_keywords(titles, top_n: int = 20):
    import re
    from collections import Counter
    cnt = Counter()
    for title in titles:
        for w in re.findall(r"[a-z][a-z\-]{2,}", str(title).lower()):
            w = w.strip("-")
            if len(w) >= 3 and w not in _ARXIV_STOPWORDS:
                cnt[w] += 1
    return cnt.most_common(top_n)


def build_arxiv_dashboard(data_dir: Path, out_dir: Path) -> Path:
    """Dashboard World Science Overview: toàn cảnh khoa học thế giới qua mẫu arXiv."""
    csv_path = out_dir / "processed_arxiv.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"Run 'process' first — no {csv_path}")

    print(f"\n[dashboard] Building arXiv world overview from {csv_path}")
    df = pd.read_csv(csv_path)
    if df.empty:
        raise ValueError("Empty arXiv dataset — scrape trước đã")

    import html as html_mod

    import plotly.express as px
    import plotly.graph_objects as go

    df["field"] = df.get("primary_category", "").fillna("").map(_arxiv_field)
    df["_pub_date"] = pd.to_datetime(df.get("published"), utc=True, errors="coerce")
    total = len(df)
    n_fields = int(df["field"].nunique())
    n_cats = int(df.get("primary_category", pd.Series(dtype=str)).nunique())
    valid_dates = df["_pub_date"].dropna()
    if not valid_dates.empty:
        date_span = f"{valid_dates.min().date()} → {valid_dates.max().date()}"
    else:
        date_span = "N/A"

    top_field = df["field"].value_counts()
    top_field_name, top_field_n = top_field.index[0], int(top_field.values[0])
    top_cat = df["primary_category"].fillna("unknown").value_counts()
    kw = _arxiv_top_keywords(df.get("title", []))
    top_kw = kw[0] if kw else ("—", 0)
    authors = pd.Series("; ".join(df.get("authors", "").fillna("")).split("; ")).str.strip()
    authors = authors[(authors != "") & (authors.str.len() > 2)]
    top_author = authors.value_counts()
    top_author_name = top_author.index[0] if not top_author.empty else "—"

    def _fig(fig, height: int = 420):
        fig.update_layout(
            height=height,
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font=dict(family="Inter, system-ui, sans-serif", color="#E8E8F0", size=13),
            xaxis=dict(gridcolor="rgba(255,255,255,0.06)", zeroline=False),
            yaxis=dict(gridcolor="rgba(255,255,255,0.06)", zeroline=False),
            margin=dict(l=20, r=20, t=50, b=20),
        )
        return fig.to_html(full_html=False, include_plotlyjs=False)

    charts: list = []

    fc = df["field"].value_counts()
    fig = px.bar(x=fc.index, y=fc.values, title="🌍 Papers theo lĩnh vực lớn",
                 color=fc.index, color_discrete_sequence=px.colors.qualitative.Bold,
                 text=fc.values)
    fig.update_layout(showlegend=False)
    fig.update_traces(textposition="outside")
    charts.append(_fig(fig))

    c15 = top_cat.head(15)
    fig = go.Figure(go.Bar(x=c15.values[::-1], y=c15.index[::-1], orientation="h",
                           marker=dict(color="#00D2FF", line_width=0),
                           text=c15.values[::-1], textposition="outside"))
    fig.update_layout(title="📚 Top 15 chuyên ngành (primary category)")
    charts.append(_fig(fig, 480))

    if not valid_dates.empty:
        per_day = df.assign(day=valid_dates.dt.date).groupby("day").size()
        fig = go.Figure(go.Scatter(x=[str(d) for d in per_day.index], y=per_day.values,
                                   mode="lines+markers", line=dict(color="#C9F65D", width=3),
                                   marker=dict(size=7)))
        fig.update_layout(title="📈 Nhịp xuất bản theo ngày (mẫu)", xaxis_title="", yaxis_title="Papers")
        charts.append(_fig(fig, 380))

    if kw:
        words, counts = zip(*kw)
        fig = go.Figure(go.Bar(x=list(counts)[::-1], y=list(words)[::-1], orientation="h",
                               marker=dict(color="#FF6B9D", line_width=0),
                               text=list(counts)[::-1], textposition="outside"))
        fig.update_layout(title="🔥 Từ khóa nóng trong tiêu đề")
        charts.append(_fig(fig, 520))

    if not top_author.empty:
        ta = top_author.head(10)
        fig = px.bar(x=ta.values, y=ta.index, orientation="h", title="✍️ Tác giả prolific nhất (mẫu)",
                     color=ta.values, color_continuous_scale="teal", text=ta.values)
        fig.update_layout(showlegend=False)
        charts.append(_fig(fig, 420))

    if "pdf_location" in df.columns and df["pdf_location"].astype(str).str.startswith("s3://").any():
        is_minio = df["pdf_location"].astype(str).str.startswith("s3://").fillna(False)
        vals = pd.Series({"MinIO (s3://)": int(is_minio.sum()), "Local": int((~is_minio).sum())})
        fig = px.pie(values=vals.values, names=vals.index, hole=0.4, title="💾 PDF Storage")
        charts.append(_fig(fig, 360))

    grid_cells = "".join(f'<div class="chart-card">{h}</div>' for h in charts)

    insights = [
        f"🌍 Mẫu <strong>{total} papers</strong> mới nhất từ "
        f"<strong>{n_fields} lĩnh vực / {n_cats} chuyên ngành</strong> ({date_span}).",
        f"🏆 <strong>{html_mod.escape(str(top_field_name))}</strong> dẫn đầu với "
        f"{top_field_n} papers ({top_field_n / total * 100:.0f}%).",
        f"📚 Chuyên ngành sôi động nhất: "
        f"<strong>{html_mod.escape(str(top_cat.index[0]))}</strong> ({int(top_cat.values[0])} papers).",
        f"🔥 Từ khóa nóng nhất tiêu đề: "
        f"<strong>{html_mod.escape(str(top_kw[0]))}</strong> ({top_kw[1]} lượt).",
        f"✍️ Tác giả xuất hiện nhiều nhất mẫu: "
        f"<strong>{html_mod.escape(str(top_author_name))}</strong>.",
    ]
    insights_html = (
        '<div class="insights-panel"><div class="insights-title">💡 Key Insights</div>'
        + "".join(f'<div class="insight-item">{s}</div>' for s in insights)
        + "</div>"
    )

    newest = df.sort_values("_pub_date", ascending=False).head(50)
    rows_html = []
    for _, r in newest.iterrows():
        aid = str(r.get("arxiv_id", ""))
        link = f"https://arxiv.org/abs/{aid}" if aid else "#"
        rows_html.append(
            "<tr><td><a href='" + link + "' target='_blank'>" + html_mod.escape(aid) + "</a></td>"
            "<td>" + html_mod.escape(str(r.get("title", ""))[:160]) + "</td>"
            "<td>" + html_mod.escape(str(r.get("primary_category", ""))) + "</td>"
            "<td>" + html_mod.escape(str(r.get("published", ""))[:10]) + "</td></tr>"
        )
    table_html = (
        "<div class='chart-card full'><h3>🆕 50 papers mới nhất</h3>"
        "<div class='table-wrap'><table><thead><tr><th>ID</th><th>Title</th><th>Cat</th><th>Date</th>"
        "</tr></thead><tbody>" + "".join(rows_html) + "</tbody></table></div></div>"
    )

    kpi = (
        '<div class="kpi-row">'
        f'<div class="kpi-card"><div class="kpi-value">{total}</div><div class="kpi-label">Papers (mẫu)</div></div>'
        f'<div class="kpi-card"><div class="kpi-value">{n_fields}</div><div class="kpi-label">Lĩnh vực</div></div>'
        f'<div class="kpi-card"><div class="kpi-value">{n_cats}</div><div class="kpi-label">Chuyên ngành</div></div>'
        f'<div class="kpi-card"><div class="kpi-value">{html_mod.escape(str(top_kw[0]))}</div>'
        '<div class="kpi-label">Keyword nóng</div></div>'
        "</div>"
    )

    css = (
        "* { margin: 0; padding: 0; box-sizing: border-box; }"
        "body { font-family: Inter, system-ui, sans-serif; background: #0a0a1a; color: #E8E8F0; }"
        ".container { max-width: 1440px; margin: 0 auto; padding: 30px 24px; }"
        ".header { text-align: center; margin-bottom: 30px; }"
        ".header h1 { font-size: 2.4rem; font-weight: 800; "
        "background: linear-gradient(135deg, #6C63FF, #00D2FF 45%, #C9F65D); "
        "-webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; }"
        ".subtitle { color: #7A7A8E; margin-top: 8px; }"
        ".subtitle code { color: #00D2FF; }"
        ".kpi-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 20px; }"
        ".kpi-card { background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); "
        "border-radius: 16px; padding: 20px; text-align: center; }"
        ".kpi-value { font-size: 1.8rem; font-weight: 800; color: #00D2FF; }"
        ".kpi-label { font-size: 0.8rem; color: #7A7A8E; text-transform: uppercase; margin-top: 4px; }"
        ".insights-panel { background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); "
        "border-radius: 16px; padding: 20px 28px; margin-bottom: 28px; }"
        ".insights-title { color: #00D2FF; font-weight: 700; margin-bottom: 10px; text-transform: uppercase; }"
        ".insight-item { padding: 6px 0; line-height: 1.6; border-bottom: 1px solid rgba(255,255,255,0.05); }"
        ".insight-item:last-child { border-bottom: none; }"
        ".insight-item strong { color: #C9F65D; }"
        ".section-title { font-size: 1.05rem; font-weight: 700; color: #6C63FF; text-transform: uppercase; "
        "letter-spacing: 1px; margin: 30px 0 16px; padding-left: 14px; border-left: 3px solid #6C63FF; }"
        ".grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 20px; }"
        ".chart-card { background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); "
        "border-radius: 16px; padding: 20px; overflow: hidden; }"
        ".chart-card.full { grid-column: 1 / -1; }"
        ".chart-card h3 { color: #00D2FF; margin-bottom: 10px; }"
        ".table-wrap { max-height: 520px; overflow: auto; }"
        "table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }"
        "th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid rgba(255,255,255,0.07); }"
        "th { color: #00D2FF; position: sticky; top: 0; background: #12122a; }"
        "td a { color: #C9F65D; text-decoration: none; }"
        ".footer { text-align: center; color: #7A7A8E; margin-top: 40px; font-size: 0.8rem; }"
        "@media (max-width: 900px) { .grid { grid-template-columns: 1fr; } "
        ".kpi-row { grid-template-columns: repeat(2, 1fr); } }"
    )

    page = (
        "<!DOCTYPE html>\n<html lang='vi'>\n<head>\n<meta charset='UTF-8'>\n"
        "<meta name='viewport' content='width=device-width, initial-scale=1.0'>\n"
        "<title>arXiv World Science Overview</title>\n"
        '<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>\n'
        "<style>" + css + "</style>\n</head>\n<body>\n<div class='container'>\n"
        "  <div class='header'><h1>🌍 World Science Overview</h1>\n"
        f"  <p class='subtitle'>Mẫu <code>{total}</code> papers arXiv mới nhất · "
        f"<code>{date_span}</code> · metadata-only "
        "(PDF/MinIO ở pipeline one-shot riêng)</p></div>\n"
        f"  {kpi}\n  {insights_html}\n"
        '  <div class="section-title">📊 Bức tranh lĩnh vực</div>' + "\n"
        f"  <div class='grid'>{grid_cells}</div>\n"
        '  <div class="section-title">🆕 Dòng chảy papers mới</div>' + "\n"
        f"  <div class='grid'>{table_html}</div>\n"
        f"  <div class='footer'>Nguồn: arXiv API (export.arxiv.org) · {total} papers · {date_span}</div>\n"
        "</div>\n</body>\n</html>"
    )

    out_html = out_dir / "arxiv_dashboard.html"
    out_html.write_text(page, encoding="utf-8")
    print(f"  → Dashboard saved: {out_html}")
    return out_html


# ─── KAGGLE PUSH ──────────────────────────────────────────────────────────────

def _default_kaggle_id(source: str) -> str:
    if source == "itviec":
        return "quangcrawler/itviec-jobs"
    if source == "arxiv":
        return "docutee/arxiv-papers"
    return "docutee/topcv-it-jobs-vietnam"


def push_to_kaggle(data_dir: Path, dataset_id: str) -> None:
    """Push processed data to Kaggle."""
    import subprocess

    print(f"\n[kaggle] Pushing to {dataset_id}")

    # Create metadata
    meta = {"title": dataset_id.split("/")[-1], "id": dataset_id, "licenses": [{"name": "CC0-1.0"}]}
    meta_path = data_dir / "dataset-metadata.json"
    meta_path.write_text(json.dumps(meta, indent=2))

    try:
        r = subprocess.run(
            ["kaggle", "datasets", "version", "-m",
             f"Auto update {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}",
             "-p", str(data_dir), "--dir-mode", "zip"],
            capture_output=True, text=True, timeout=300,
        )
        if r.returncode == 0:
            print(f"  → Kaggle push SUCCESS\n{r.stdout}")
        else:
            print(f"  → Version failed, trying create: {r.stderr}")
            r2 = subprocess.run(
                ["kaggle", "datasets", "create", "-p", str(data_dir), "--dir-mode", "zip"],
                capture_output=True, text=True, timeout=300,
            )
            print(f"  → {'SUCCESS' if r2.returncode == 0 else 'FAILED'}: {r2.stdout or r2.stderr}")
    except FileNotFoundError:
        print("  → [WARN] kaggle CLI not found. Install: pip install kaggle")
    except subprocess.TimeoutExpired:
        print("  → [WARN] Kaggle push timed out")


if __name__ == "__main__":
    main()
