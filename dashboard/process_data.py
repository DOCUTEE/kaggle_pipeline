#!/usr/bin/env python3
"""Data processing pipeline for ITviec job data.

Steps:
  1. Load raw JSON
  2. Clean & normalize fields
  3. Feature engineering (seniority, skill categories, salary parsing)
  4. Export processed CSV for dashboard consumption

Usage:
  python process_data.py [DATA_DIR]
  DATA_DIR defaults to "." (expects itviec_jobs_latest.json in that dir)
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pandas as pd

# ─── CONFIG ───────────────────────────────────────────────────────────────────
DATA_DIR = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
RAW_JSON = DATA_DIR / "itviec_jobs_latest.json"
OUT_DIR = DATA_DIR
PROCESSED_CSV = OUT_DIR / "processed_jobs.csv"

# ─── SKILL TAXONOMY ───────────────────────────────────────────────────────────
# Group raw tags into high-level skill categories for better analytics
SKILL_CATEGORIES = {
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

# Reverse map: skill → category
SKILL_TO_CATEGORY: dict[str, str] = {}
for cat, skills in SKILL_CATEGORIES.items():
    for s in skills:
        SKILL_TO_CATEGORY[s.lower()] = cat


# ─── SENIORITY EXTRACTION ─────────────────────────────────────────────────────
def extract_seniority(title: str, job_function: str) -> str:
    """Extract seniority level from title or job function."""
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

    # Try to extract YoE from title
    yoe_match = re.search(r"(\d+)\+?\s*(?:yoe|years?)", text)
    if yoe_match:
        years = int(yoe_match.group(1))
        if years <= 2:
            return "Fresher/Junior"
        elif years <= 4:
            return "Mid-level"
        else:
            return "Senior/Lead"

    return "Not specified"


# ─── POSTED TIME NORMALIZATION ────────────────────────────────────────────────
def parse_posted_hours(posted: str) -> float | None:
    """Convert '3 hours ago', '2 days ago' etc. to hours."""
    if not posted:
        return None
    m = re.search(r"(\d+)\s*(minute|hour|day|week|month)", posted.lower())
    if not m:
        return None
    val = int(m.group(1))
    unit = m.group(2)
    if unit.startswith("minute"):
        return val / 60
    elif unit.startswith("hour"):
        return float(val)
    elif unit.startswith("day"):
        return val * 24
    elif unit.startswith("week"):
        return val * 24 * 7
    elif unit.startswith("month"):
        return val * 24 * 30
    return None


# ─── MAIN PROCESSING ─────────────────────────────────────────────────────────
def process() -> pd.DataFrame:
    """Load, clean, enrich, and save processed data."""
    # 1. Load
    with open(RAW_JSON) as f:
        raw = json.load(f)
    jobs = raw["jobs"]
    print(f"Loaded {len(jobs)} jobs from {RAW_JSON}")

    df = pd.DataFrame(jobs)

    # 2. Clean
    df["salary"] = df["salary"].replace("Sign in to view salary", "")
    df["tags"] = df["tags"].apply(lambda x: x if isinstance(x, list) else [])
    df["highlights"] = df["highlights"].apply(lambda x: x if isinstance(x, list) else [])
    df["tags_str"] = df["tags"].apply(lambda x: " | ".join(x))

    # 3. Feature engineering
    df["seniority"] = df.apply(
        lambda r: extract_seniority(r["title"], r["job_function"]), axis=1
    )

    df["posted_hours_ago"] = df["posted_time"].apply(parse_posted_hours)

    # Skill categories
    def assign_categories(tags: list[str]) -> list[str]:
        cats = set()
        for tag in tags:
            cat = SKILL_TO_CATEGORY.get(tag.lower())
            if cat:
                cats.add(cat)
        return sorted(cats)

    df["skill_categories"] = df["tags"].apply(assign_categories)
    df["skill_categories_str"] = df["skill_categories"].apply(lambda x: " | ".join(x))
    df["num_categories"] = df["skill_categories"].apply(len)

    # Location normalization
    def normalize_location(loc: str) -> str:
        loc = loc.strip()
        if not loc:
            return "Unknown"
        if "ho chi minh" in loc.lower() and "ha noi" in loc.lower():
            return "HCM + Ha Noi"
        if "ho chi minh" in loc.lower():
            return "Ho Chi Minh"
        if "ha noi" in loc.lower():
            return "Ha Noi"
        if "da nang" in loc.lower():
            return "Da Nang"
        return loc

    df["location_clean"] = df["location"].apply(normalize_location)

    # Number of tags
    df["num_tags"] = df["tags"].apply(len)

    # Has highlights
    df["has_highlights"] = df["highlights"].apply(len) > 0

    # Label
    df["label_clean"] = df["label"].fillna("").replace("", "None")

    # 4. Save
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(PROCESSED_CSV, index=False)
    print(f"Saved processed data -> {PROCESSED_CSV} ({len(df)} rows)")

    # Print summary
    print("\n=== DATA SUMMARY ===")
    print(f"Total jobs: {len(df)}")
    print(f"\nBy location:\n{df['location_clean'].value_counts().to_string()}")
    print(f"\nBy seniority:\n{df['seniority'].value_counts().to_string()}")
    print(f"\nBy working type:\n{df['working_type'].value_counts().to_string()}")
    print(f"\nBy label:\n{df['label_clean'].value_counts().to_string()}")
    print(f"\nSkill categories distribution:")
    all_cats = df["skill_categories"].explode().dropna()
    print(all_cats.value_counts().head(15).to_string())

    return df


if __name__ == "__main__":
    process()
