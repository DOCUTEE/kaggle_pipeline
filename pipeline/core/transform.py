"""Schema chuẩn + derived features — dùng chung cho mọi source.

**Schema chuẩn** (`PROCESSED_CORE_FIELDS`) là hợp đồng dữ liệu giữa 3 tầng:
    scrape → process → (dashboard | Postgres | Kaggle)

Mọi source phải ra đúng các cột core này; cột đặc thù của từng source được
giữ thêm ở cuối (vd `working_type` của itviec, `is_hot` của topcv) nên vẫn
join/so sánh được giữa 2 nguồn.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable, Sequence

import pandas as pd

from pipeline.core.snapshot import atomic_write_json, split_list

#: Các cột raw tối thiểu mà 1 row do scraper trả về phải có.
CANONICAL_RAW_FIELDS: tuple[str, ...] = (
    "job_id",
    "title",
    "company",
    "url",
    "salary",
    "location",
    "skills",
    "posted_date",
    "scraped_at",
    "source",
)

#: Cột core của processed CSV (thứ tự cố định cho mọi source).
PROCESSED_CORE_FIELDS: tuple[str, ...] = (
    "job_id",
    "title",
    "company",
    "url",
    "salary",
    "location",
    "location_clean",
    "skills",
    "num_skills",
    "skill_categories",
    "seniority",
    "posted_date",
    "posted_hours_ago",
    "scraped_at",
    "source",
)

SENIORITY_ORDER: tuple[str, ...] = (
    "Intern",
    "Fresher/Junior",
    "Mid-level",
    "Not specified",
    "Senior/Lead",
    "Staff/Architect",
    "Manager+",
)

SALARY_PLACEHOLDERS = ("Sign in to view salary", "Đăng nhập để xem lương")

#: Tên cột của các bản scraper CŨ → tên canonical (migration shim).
#: Snapshot cũ trên server (itviec dùng job_key/tags/posted_time) vẫn process được.
LEGACY_ALIASES: dict[str, str] = {
    "job_key": "job_id",
    "tags": "skills",
    "posted_time": "posted_date",
}

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

_SKILL_TO_CATEGORY: dict[str, str] = {
    skill.lower(): category
    for category, skills in SKILL_CATEGORIES.items()
    for skill in skills
}

# ─── RAW → DATAFRAME ─────────────────────────────────────────────────────────


def find_raw_json(data_dir: Path, prefix: str) -> Path:
    """Tìm raw JSON mới nhất của 1 source (ưu tiên `*_latest.json`)."""
    data_dir = Path(data_dir)
    latest = data_dir / f"{prefix}_latest.json"
    if latest.exists():
        return latest
    candidates = sorted(data_dir.glob(f"{prefix}_*.json"))
    if not candidates:
        raise FileNotFoundError(f"Không tìm thấy raw JSON của {prefix!r} trong {data_dir}")
    return candidates[-1]


def load_raw_jobs(raw_json: Path) -> list[dict]:
    """Đọc snapshot JSON chuẩn (`{"jobs": [...]}` hoặc `[...]`)."""
    with open(raw_json, encoding="utf-8") as f:
        payload = json.load(f)
    jobs = payload.get("jobs", payload) if isinstance(payload, dict) else payload
    if not isinstance(jobs, list):
        raise ValueError(f"Raw JSON sai định dạng: {raw_json}")
    return jobs


# ─── FEATURE ENGINEERING ─────────────────────────────────────────────────────


def extract_seniority(title: str, *context: str) -> str:
    """Suy ra cấp bậc từ title + level/experience (hỗ trợ cả tiếng Việt).

    Thứ tự xét: intern → junior → senior → manager → staff → mid → số năm.
    (Senior xét trước mid để 'Middle/Senior X' vẫn ra Senior/Lead như bản cũ.)
    """
    text = " ".join(str(part) for part in (title, *context) if part).lower()
    if any(w in text for w in ("intern", "internship", "thực tập")):
        return "Intern"
    if any(w in text for w in ("fresher", "junior", "entry level")):
        return "Fresher/Junior"
    if any(w in text for w in ("senior", "sr.", "sr ", "lead", "principal", "cao cấp", "trưởng nhóm")):
        return "Senior/Lead"
    if any(w in text for w in ("manager", "director", "head", "vp", "cto", "trưởng phòng", "giám đốc", "quản lý")):
        return "Manager+"
    if any(w in text for w in ("staff", "architect")):
        return "Staff/Architect"
    if any(w in text for w in ("mid level", "mid-level", "middle")):
        return "Mid-level"
    m = re.search(r"(\d+)\+?\s*(?:yoe|years?|năm)", text)
    if m:
        years = int(m.group(1))
        return "Fresher/Junior" if years <= 2 else ("Mid-level" if years <= 4 else "Senior/Lead")
    return "Not specified"


def parse_posted_hours(posted: Any) -> float | None:
    """Đổi 'đăng 3 giờ trước' / '3 hours ago' → số giờ (None nếu không parse được)."""
    if not isinstance(posted, str) or not posted:
        return None
    text = posted.lower()
    m = re.search(r"(\d+)\s*(phút|giờ|ngày|tuần|tháng|minute|hour|day|week|month)", text)
    if not m:
        return None
    value, unit = int(m.group(1)), m.group(2)
    if unit.startswith(("minute", "phút")):
        return value / 60
    if unit.startswith(("hour", "giờ")):
        return float(value)
    if unit.startswith(("day", "ngày")):
        return value * 24
    if unit.startswith(("week", "tuần")):
        return value * 24 * 7
    if unit.startswith(("month", "tháng")):
        return value * 24 * 30
    return None


def normalize_location(loc: Any) -> str:
    """Chuẩn hoá location về các thành phố chính (dùng chung 2 nguồn)."""
    text = str(loc or "").strip()
    if not text or text.lower() in ("nan", "none"):
        return "Unknown"
    low = text.lower()
    has_hcm = "ho chi minh" in low or "hồ chí minh" in low or "hcm" in low
    has_hn = "ha noi" in low or "hà nội" in low
    if has_hcm and has_hn:
        return "HCM + Ha Noi"
    if has_hcm:
        return "Ho Chi Minh"
    if has_hn:
        return "Ha Noi"
    if "da nang" in low or "đà nẵng" in low:
        return "Da Nang"
    return text


def categorize_skills(skills: Iterable[str]) -> list[str]:
    """Gán nhóm kỹ năng cho từng skill (theo taxonomy dùng chung)."""
    categories = {
        _SKILL_TO_CATEGORY[s.lower()]
        for s in skills
        if isinstance(s, str) and s.lower() in _SKILL_TO_CATEGORY
    }
    return sorted(categories)


# ─── BUILD PROCESSED DATAFRAME ───────────────────────────────────────────────


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return split_list(value)


def _clean_salary(value: Any) -> str:
    text = str(value or "").strip()
    if text.lower() in ("nan", "none"):
        return ""
    for placeholder in SALARY_PLACEHOLDERS:
        if placeholder.lower() in text.lower():
            return ""
    return text


def _apply_legacy_aliases(df: pd.DataFrame) -> pd.DataFrame:
    """Đổi tên cột của snapshot cũ (job_key/tags/posted_time) về tên canonical."""
    for legacy, canonical in LEGACY_ALIASES.items():
        if legacy not in df.columns:
            continue
        if canonical not in df.columns:
            df = df.rename(columns={legacy: canonical})
            continue
        # canonical đã có → chỉ điền vào chỗ trống rồi bỏ cột cũ
        empty = df[canonical].isna() | (df[canonical].astype(str).str.strip() == "")
        df.loc[empty, canonical] = df.loc[empty, legacy]
        df = df.drop(columns=[legacy])
    return df


def build_processed_df(rows: Sequence[dict], *, source: str) -> pd.DataFrame:
    """Raw rows → processed DataFrame theo schema chuẩn.

    Bước này giống nhau cho mọi source: clean → derive → reorder cột.
    Phần đặc thù source chỉ nằm ở `rows` (adapter map ra canonical raw fields).
    """
    if not rows:
        return pd.DataFrame(columns=list(PROCESSED_CORE_FIELDS))

    df = _apply_legacy_aliases(pd.DataFrame(list(rows)))

    # 1. Đảm bảo các cột canonical luôn tồn tại
    for field in CANONICAL_RAW_FIELDS:
        if field not in df.columns:
            df[field] = ""
    df["source"] = df["source"].replace("", source).fillna(source)

    # 2. Clean
    df["salary"] = df["salary"].apply(_clean_salary)
    df["skills"] = df["skills"].apply(_as_list)
    df["title"] = df["title"].fillna("").astype(str).str.strip()
    df["company"] = df["company"].fillna("").astype(str).str.strip()
    df = df[df["title"].astype(bool)]  # bỏ row không có title

    if df.empty:
        return pd.DataFrame(columns=list(PROCESSED_CORE_FIELDS))

    # 3. Derived features (giống nhau cho mọi source)
    context_cols = [c for c in ("level", "experience", "job_function", "category") if c in df.columns]
    df["seniority"] = df.apply(
        lambda r: extract_seniority(r["title"], *(r[c] for c in context_cols)), axis=1
    )
    df["posted_hours_ago"] = df["posted_date"].apply(parse_posted_hours)
    df["skill_categories"] = df["skills"].apply(categorize_skills)
    df["location_clean"] = df["location"].apply(normalize_location)
    df["num_skills"] = df["skills"].apply(len)
    if "highlights" in df.columns:
        df["highlights"] = df["highlights"].apply(_as_list)
        df["has_highlights"] = df["highlights"].apply(len) > 0
    if "label" in df.columns:
        df["label_clean"] = df["label"].fillna("").replace("", "None")
    if "job_id" in df.columns:
        df["job_id"] = df["job_id"].fillna("").astype(str)

    # 4. Cột core lên trước, cột riêng của source giữ nguyên phía sau
    core = [c for c in PROCESSED_CORE_FIELDS if c in df.columns]
    extras = [c for c in df.columns if c not in core]
    return df[core + extras]


def write_processed_json(df: pd.DataFrame, out_dir: Path, filename: str) -> Path:
    """Ghi processed JSON — list/bool/số giữ nguyên kiểu, không cần join chuỗi."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / filename

    jobs = json.loads(
        df.to_json(orient="records", force_ascii=False, date_format="iso", default_handler=str)
    )
    payload = {
        "source": str(df["source"].iloc[0]) if len(df) and "source" in df.columns else "",
        "total_jobs": len(jobs),
        "jobs": jobs,
    }
    return atomic_write_json(path, payload)


def load_processed_df(path: Path) -> pd.DataFrame:
    """Đọc processed JSON (chấp nhận cả `{"jobs": [...]}` lẫn `[...]`)."""
    with open(Path(path), encoding="utf-8") as f:
        payload = json.load(f)
    rows = payload.get("jobs", payload) if isinstance(payload, dict) else payload
    df = pd.DataFrame(rows)
    for col in ("skills", "skill_categories", "highlights"):
        if col in df.columns:
            df[col] = df[col].apply(_as_list)
    return df


__all__ = [
    "CANONICAL_RAW_FIELDS",
    "PROCESSED_CORE_FIELDS",
    "SENIORITY_ORDER",
    "SKILL_CATEGORIES",
    "build_processed_df",
    "categorize_skills",
    "extract_seniority",
    "find_raw_json",
    "load_processed_df",
    "load_raw_jobs",
    "normalize_location",
    "parse_posted_hours",
    "write_processed_json",
]
