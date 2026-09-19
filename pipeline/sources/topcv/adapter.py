"""TopCV adapter — cùng `BaseSource` contract như itviec.

Bọc scraper của source (Playwright: client + parser + models + scraper) và map `Job` sang schema
chuẩn. Nhờ vậy TopCV có cùng feature engineering + cùng dashboard shell như
itviec, chỉ khác danh sách chart (do dữ liệu có cột khác).
"""

from __future__ import annotations

import logging
from pathlib import Path

from pipeline import settings
from pipeline.core.contracts import PROCESSED_JSON, DbSpec, ProcessResult, ScrapeResult
from pipeline.core.dashboard import (
    ChartSpec,
    KpiSpec,
    Section,
    render_dashboard,
    standard_kpis,
)
from pipeline.core.publish import now_iso
from pipeline.core.snapshot import SnapshotStore
from pipeline.core.transform import (
    build_processed_df,
    find_raw_json,
    load_processed_df,
    load_raw_jobs,
    write_processed_json,
)
from pipeline.sources.base import BaseSource

logger = logging.getLogger(__name__)

#: Field của raw snapshot (canonical + cột riêng của topcv).
RAW_FIELDS = (
    "job_id", "title", "company", "url", "salary", "location",
    "skills", "posted_date", "scraped_at", "source",
    "company_url", "experience", "level", "job_type", "category",
    "deadline", "is_hot", "is_urgent", "scrape_date",
)

SENIOR_PLUS = ("Senior/Lead", "Staff/Architect", "Manager+")

SECTIONS = [
    Section("📍 Geographic Distribution", (
        ChartSpec("bar_v", "📍 Jobs by Location", "location_clean"),
        ChartSpec("stacked", "📊 Seniority × Location", "location_clean", second="seniority"),
    )),
    Section("👤 Job Profile", (
        ChartSpec("pie", "🎯 Seniority Breakdown", "seniority"),
        ChartSpec("hist", "⏰ Job Freshness", "posted_hours_ago"),
        ChartSpec("bar_v", "🏷️ Job Level", "level"),
        ChartSpec("bar_v", "🧾 Job Type", "job_type"),
    )),
    Section("🛠️ Skills & Technologies", (
        ChartSpec("bar_h", "🛠️ Top 20 Skills in Demand", "skills", top=20, full=True, list_column=True),
        ChartSpec("bar_v", "📚 Skill Categories", "skill_categories", list_column=True),
        ChartSpec("cooccurrence", "🔗 Skill Co-occurrence", "skills", list_column=True),
    )),
    Section("🏢 Companies, Salary & Cross-analysis", (
        ChartSpec("bar_v", "🏢 Top 15 Hiring Companies", "company", top=15),
        ChartSpec("bar_v", "💰 Salary Distribution", "salary", top=12),
        ChartSpec("bar_v", "🗂️ Job Category", "category"),
        ChartSpec("heatmap", "🗺️ Skills × Seniority Heatmap", "skills", second="seniority", full=True),
    )),
]

KPIS = standard_kpis(
    KpiSpec("🔥", "Hot Jobs", "sum_true", column="is_hot", flag="hot"),
    KpiSpec("⚡", "Urgent", "sum_true", column="is_urgent"),
    KpiSpec("🎯", "Senior+", "share", column="seniority", values=SENIOR_PLUS),
)


class TopcvSource(BaseSource):
    """Adapter cho topcv.vn."""

    name = "topcv"

    # ─── 1. SCRAPE ───────────────────────────────────────────────────
    def scrape(
        self,
        data_dir: Path,
        *,
        max_pages: int | None = 50,
        workers: int = 1,  # Playwright chạy tuần tự, giữ param cho đồng nhất interface
        timeout: int = 30,
        verbose: bool = False,
    ) -> ScrapeResult:
        from .scraper import TopCvScraper

        _ = (workers, timeout, verbose)  # chưa dùng, giữ để interface đồng nhất
        data_dir = Path(data_dir)
        prefix = settings.get_source(self.name).raw_prefix

        scraper = TopCvScraper(headless=True)
        stats, jobs = scraper.scrape_all(max_pages=max_pages or 50)

        if stats.pages_failed:
            logger.warning(
                "TopCV incomplete: %d/%d pages failed: %s",
                len(stats.pages_failed), stats.total_pages, stats.pages_failed,
            )
        if not jobs:
            logger.warning("TopCV scraped 0 jobs")
            return ScrapeResult(source=self.name, count=0, raw_dir=data_dir)

        scraped_at = now_iso()
        snapshot = SnapshotStore(
            data_dir, prefix, key_field="job_id", source=self.name,
        ).save([self._to_row(job, scraped_at) for job in jobs])

        return ScrapeResult(
            source=self.name,
            count=snapshot.total,
            raw_dir=data_dir,
            latest_json=data_dir / f"{prefix}_latest.json",
        )

    @staticmethod
    def _to_row(job, scraped_at: str) -> dict:
        """pipeline.sources.topcv.models.Job → row canonical (raw schema)."""
        return {
            "job_id": job.job_id or job.url,
            "title": job.title,
            "company": job.company,
            "url": job.url,
            "salary": job.salary,
            "location": job.location,
            "skills": list(job.skills or []),
            "posted_date": job.posted_date,
            "scraped_at": scraped_at,
            "source": "topcv",
            # cột riêng của topcv
            "company_url": job.company_url,
            "experience": job.experience,
            "level": job.level,
            "job_type": job.job_type,
            "category": job.category,
            "deadline": job.deadline,
            "is_hot": job.is_hot,
            "is_urgent": job.is_urgent,
            "scrape_date": job.scrape_date,
        }

    # ─── 2. PROCESS ──────────────────────────────────────────────────
    def process(self, data_dir: Path, out_dir: Path) -> ProcessResult:
        prefix = settings.get_source(self.name).raw_prefix
        raw_json = find_raw_json(Path(data_dir), prefix)
        print(f"\n[process] Loading {raw_json}")

        rows = load_raw_jobs(raw_json)
        df = build_processed_df(rows, source=self.name)
        print(f"  → {len(df)} jobs loaded")

        json_path = write_processed_json(df, Path(out_dir), PROCESSED_JSON)
        print(f"  → Saved {json_path} ({len(df)} rows)")
        return ProcessResult(source=self.name, rows=len(df), json_path=json_path)

    # ─── 3. DASHBOARD ────────────────────────────────────────────────
    def dashboard(self, processed: ProcessResult, out_dir: Path) -> Path:
        print(f"\n[dashboard] Building TopCV dashboard from {processed.json_path}")
        df = load_processed_df(processed.json_path)
        out_html = render_dashboard(
            df=df,
            out_path=Path(out_dir) / "topcv_dashboard.html",
            heading="🇻🇳 TopCV IT Jobs",
            page_title="TopCV Job Market Dashboard",
            sections=SECTIONS,
            kpis=KPIS,
            data_url="https://www.topcv.vn",
            data_label="topcv.vn",
            source_label="TopCV",
        )
        print(f"  → Dashboard saved: {out_html}")
        return out_html

    # ─── 4. POSTGRES ─────────────────────────────────────────────────
    def db_spec(self) -> DbSpec:
        return DbSpec(
            table="topcv_jobs",
            columns={
                "job_id": "job_id",
                "title": "title",
                "company": "company",
                "salary": "salary",
                "location": "location",
                "location_clean": "location_clean",
                "experience": "experience",
                "level": "level",
                "seniority": "seniority",
                "skills": "skills",
                "skill_categories": "skill_categories",
                "num_skills": "num_skills",
                "url": "url",
                "is_hot": "is_hot",
                "posted_date": "posted_date",
                "posted_hours_ago": "posted_hours_ago",
                "scrape_date": "scrape_date",
            },
            conflict_key="job_id",
            update_columns=("title", "salary", "skills", "seniority", "scrape_date"),
            json_columns=("skill_categories",),
            bool_columns=("is_hot",),
            text_columns=("job_id",),
        )

    def load_db(self, processed: ProcessResult) -> int:
        from pipeline import db

        return db.load_processed(processed.json_path, self.db_spec())

    # ─── 5. KAGGLE STAGING ───────────────────────────────────────────
    def staging_files(self, data_dir: Path, dashboard_dir: Path) -> dict[Path, str]:
        prefix = settings.get_source(self.name).raw_prefix
        data_dir, dashboard_dir = Path(data_dir), Path(dashboard_dir)
        return {
            data_dir / f"{prefix}_latest.json": f"{self.name}_jobs.json",
            dashboard_dir / PROCESSED_JSON: PROCESSED_JSON,
        }


__all__ = ["TopcvSource"]
