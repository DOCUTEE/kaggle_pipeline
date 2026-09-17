#!/usr/bin/env python3
"""
TopCV Job Market Dashboard
Streamlit app for visualizing IT job data from topcv.vn
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from pathlib import Path
from datetime import datetime
import json
import os

# Config
st.set_page_config(
    page_title="TopCV IT Jobs Dashboard",
    page_icon="💼",
    layout="wide",
)

DATA_DIR = Path(__file__).parent.parent / "data" / "raw" / "topcv"


@st.cache_data(ttl=3600)  # Cache for 1 hour
def load_data():
    """Load the latest job data."""
    latest_csv = DATA_DIR / "topcv_jobs_latest.csv"
    if latest_csv.exists():
        df = pd.read_csv(latest_csv)
        return df

    # Fallback: try to find any CSV file
    csv_files = sorted(DATA_DIR.glob("topcv_jobs_*.csv"), reverse=True)
    if csv_files:
        df = pd.read_csv(csv_files[0])
        return df

    return pd.DataFrame()


def main():
    st.title("💼 TopCV IT Jobs Vietnam - Dashboard")
    st.markdown("Daily updated IT job market data from [topcv.vn](https://www.topcv.vn)")

    # Load data
    df = load_data()

    if df.empty:
        st.warning("⚠️ No data available. Run the scraper first!")
        st.code("python pipeline/daily_pipeline.py", language="bash")
        return

    # Sidebar filters
    st.sidebar.header("🔍 Filters")

    # Date filter
    if "scrape_date" in df.columns:
        dates = sorted(df["scrape_date"].dropna().unique())
        selected_date = st.sidebar.selectbox("Scrape Date", ["All"] + dates)
        if selected_date != "All":
            df = df[df["scrape_date"] == selected_date]

    # Location filter
    if "location" in df.columns:
        locations = sorted(df["location"].dropna().unique())
        selected_locations = st.sidebar.multiselect("Location", locations, default=locations[:5])
        if selected_locations:
            df = df[df["location"].isin(selected_locations)]

    # Company filter
    if "company" in df.columns:
        companies = sorted(df["company"].dropna().unique())
        selected_companies = st.sidebar.multiselect("Company", companies[:50])
        if selected_companies:
            df = df[df["company"].isin(selected_companies)]

    # Search by keyword
    keyword = st.sidebar.text_input("🔍 Search Job Title")
    if keyword:
        df = df[df["title"].str.contains(keyword, case=False, na=False)]

    # Main metrics
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("📋 Total Jobs", len(df))
    with col2:
        st.metric("🏢 Companies", df["company"].nunique() if "company" in df.columns else 0)
    with col3:
        st.metric("📍 Locations", df["location"].nunique() if "location" in df.columns else 0)
    with col4:
        hot_count = df["is_hot"].sum() if "is_hot" in df.columns else 0
        st.metric("🔥 Hot Jobs", int(hot_count))

    st.divider()

    # Charts row 1
    col_left, col_right = st.columns(2)

    with col_left:
        st.subheader("📊 Jobs by Location")
        if "location" in df.columns:
            location_counts = df["location"].value_counts().head(10)
            fig = px.bar(
                x=location_counts.values,
                y=location_counts.index,
                orientation="h",
                labels={"x": "Number of Jobs", "y": "Location"},
                color=location_counts.values,
                color_continuous_scale="viridis",
            )
            fig.update_layout(height=400, showlegend=False)
            st.plotly_chart(fig, use_container_width=True)

    with col_right:
        st.subheader("🏢 Top Companies")
        if "company" in df.columns:
            company_counts = df["company"].value_counts().head(10)
            fig = px.pie(
                values=company_counts.values,
                names=company_counts.index,
                hole=0.3,
            )
            fig.update_layout(height=400)
            st.plotly_chart(fig, use_container_width=True)

    # Charts row 2
    col_left2, col_right2 = st.columns(2)

    with col_left2:
        st.subheader("💰 Salary Distribution")
        if "salary" in df.columns:
            salary_data = df[df["salary"] != "Thỏa thuận"]["salary"].value_counts().head(10)
            if not salary_data.empty:
                fig = px.bar(
                    x=salary_data.index,
                    y=salary_data.values,
                    labels={"x": "Salary Range", "y": "Count"},
                    color=salary_data.values,
                    color_continuous_scale="blues",
                )
                fig.update_layout(height=400, xaxis_tickangle=45)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No salary data available")

    with col_right2:
        st.subheader("🏷️ Top Skills")
        if "skills" in df.columns:
            all_skills = []
            for skills in df["skills"].dropna():
                if isinstance(skills, str):
                    all_skills.extend([s.strip() for s in skills.split("|") if s.strip()])
            if all_skills:
                skill_counts = pd.Series(all_skills).value_counts().head(15)
                fig = px.bar(
                    x=skill_counts.index,
                    y=skill_counts.values,
                    labels={"x": "Skill", "y": "Demand Count"},
                    color=skill_counts.values,
                    color_continuous_scale="teal",
                )
                fig.update_layout(height=400, xaxis_tickangle=45)
                st.plotly_chart(fig, use_container_width=True)

    # Experience & Level distribution
    col_exp, col_level = st.columns(2)

    with col_exp:
        st.subheader("📈 Experience Requirements")
        if "experience" in df.columns:
            exp_counts = df["experience"].value_counts().head(8)
            if not exp_counts.empty:
                fig = px.pie(values=exp_counts.values, names=exp_counts.index, hole=0.4)
                fig.update_layout(height=350)
                st.plotly_chart(fig, use_container_width=True)

    with col_level:
        st.subheader("📊 Job Levels")
        if "level" in df.columns:
            level_counts = df["level"].value_counts().head(8)
            if not level_counts.empty:
                fig = px.pie(values=level_counts.values, names=level_counts.index, hole=0.4)
                fig.update_layout(height=350)
                st.plotly_chart(fig, use_container_width=True)

    # Job listings table
    st.divider()
    st.subheader("📋 Job Listings")

    display_cols = ["title", "company", "salary", "location", "experience", "level", "posted_date"]
    display_cols = [c for c in display_cols if c in df.columns]

    if display_cols:
        # Add URL column
        if "url" in df.columns:
            display_cols_with_url = display_cols + ["url"]
        else:
            display_cols_with_url = display_cols

        st.dataframe(
            df[display_cols_with_url].head(100),
            use_container_width=True,
            height=500,
        )

    # Download button
    st.divider()
    col_dl1, col_dl2 = st.columns(2)
    with col_dl1:
        csv_export = df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "📥 Download CSV",
            csv_export,
            f"topcv_jobs_{datetime.now().strftime('%Y%m%d')}.csv",
            "text/csv",
        )
    with col_dl2:
        json_export = df.to_json(orient="records", force_ascii=False, indent=2)
        st.download_button(
            "📥 Download JSON",
            json_export.encode("utf-8"),
            f"topcv_jobs_{datetime.now().strftime('%Y%m%d')}.json",
            "application/json",
        )

    # Footer
    st.divider()
    st.caption(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M')} | Source: topcv.vn")


if __name__ == "__main__":
    main()
