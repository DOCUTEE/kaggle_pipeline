"""ITviec source adapter — implement `BaseSource` đầy đủ 6 method.

Bọc package `itviec/` (client + parser + models + runner) và map kết quả parse
sang schema chuẩn ở `pipeline/core/transform.py`.

Không có logic pipeline riêng ở đây: scrape → rows → SnapshotStore (core),
process → build_processed_df (core), dashboard → render_dashboard (core).
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

#: Field của raw snapshot (canonical + cột riêng của itviec).
RAW_FIELDS = (
    "job_id", "title", "company", "url", "salary", "location",
    "skills", "posted_date", "scraped_at", "source",
    "job_function", "working_type", "label", "highlights", "page",
)

SENIOR_PLUS = ("Senior/Lead", "Staff/Architect", "Manager+")

SECTIONS = [
    Section("📍 Geographic Distribution", (
        ChartSpec("bar_v", "📍 Jobs by Location", "location_clean"),
        ChartSpec("stacked", "🏠 Working Type × Location", "location_clean", second="working_type"),
    )),
    Section("👤 Job Profile", (
        ChartSpec("pie", "🎯 Seniority Breakdown", "seniority"),
        ChartSpec("pie", "🏢 Work Mode", "working_type"),
        ChartSpec("pie", "🔥 Job Urgency Labels", "label_clean"),
        ChartSpec("hist", "⏰ Job Freshness", "posted_hours_ago"),
    )),
    Section("🛠️ Skills & Technologies", (
        ChartSpec("bar_h", "🛠️ Top 20 Skills in Demand", "skills", top=20, full=True, list_column=True),
        ChartSpec("bar_v", "📚 Skill Categories", "skill_categories", list_column=True),
        ChartSpec("cooccurrence", "🔗 Skill Co-occurrence", "skills", list_column=True),
    )),
    Section("🏢 Companies & Cross-analysis", (
        ChartSpec("bar_v", "🏢 Top 15 Hiring Companies", "company", top=15),
        ChartSpec("stacked", "📊 Seniority × Location", "location_clean", second="seniority"),
        ChartSpec("heatmap", "🗺️ Skills × Seniority Heatmap", "skills", second="seniority", full=True),
    )),
]

KPIS = standard_kpis(
    KpiSpec("🔥", "Hot Jobs", "share", column="label_clean", values=("HOT", "SUPER HOT"), flag="hot"),
    KpiSpec("🏠", "Remote", "share", column="working_type", values=("Remote",)),
    KpiSpec("🎯", "Senior+", "share", column="seniority", values=SENIOR_PLUS),
)


class ItviecSource(BaseSource):
    """Adapter cho itviec.com."""

    name = "itviec"

    # ─── 1. SCRAPE ───────────────────────────────────────────────────
    def scrape(
        self,
        data_dir: Path,
        *,
        max_pages: int | None = None,
        workers: int = 4,
        timeout: int = 30,
        verbose: bool = False,
    ) -> ScrapeResult:
        from itviec.client import AccessDeniedError, ItviecClient
        from itviec.runner import ScrapeRunner

        data_dir = Path(data_dir)
        prefix = settings.get_source(self.name).raw_prefix

        client = ItviecClient(timeout=timeout)
        runner = ScrapeRunner(client, workers=workers)
        try:
            stats, jobs = runner.run(max_pages=max_pages)
        except AccessDeniedError:
            logger.exception("ITviec access denied")
            raise

        if stats.pages_failed:
            logger.warning(
                "ITviec incomplete: %d/%d pages failed: %s",
                len(stats.pages_failed), stats.total_pages, stats.pages_failed,
            )

        snapshot = SnapshotStore(
            data_dir, prefix, key_field="job_id", source=self.name,
        ).save([self._to_row(job) for job in jobs], run_id=runner.run_id)

        return ScrapeResult(
            source=self.name,
            count=snapshot.total,
            raw_dir=data_dir,
            latest_json=data_dir / f"{prefix}_latest.json",
            extra={
                "pages_fetched": stats.pages_fetched,
                "pages_failed": list(stats.pages_failed),
            },
        )

    @staticmethod
    def _to_row(job) -> dict:
        """itviec.models.Job → row canonical (raw schema)."""
        return {
            "job_id": job.job_key or job.url,
            "title": job.title,
            "company": job.company,
            "url": job.url,
            "salary": job.salary,
            "location": job.location,
            "skills": list(job.tags),
            "posted_date": job.posted_time,
            "scraped_at": job.scraped_at,
            "source": "itviec",
            # cột riêng của itviec
            "job_function": job.job_function,
            "working_type": job.working_type.value,
            "label": job.label.value,
            "highlights": list(job.highlights),
            "page": job.page,
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
        print(f"\n[dashboard] Building iTViec dashboard from {processed.json_path}")
        df = load_processed_df(processed.json_path)
        out_html = render_dashboard(
            df=df,
            out_path=Path(out_dir) / "itviec_dashboard.html",
            heading="🇻🇳 ITviec Job Market",
            page_title="ITviec Job Market Dashboard",
            sections=SECTIONS,
            kpis=KPIS,
            data_url="https://itviec.com",
            data_label="itviec.com",
            source_label="ITviec",
        )
        print(f"  → Dashboard saved: {out_html}")
        print(f"  → Open: file://{out_html.resolve()}")
        return out_html

    # ─── 4. POSTGRES ─────────────────────────────────────────────────
    def db_spec(self) -> DbSpec:
        return DbSpec(
            table="itviec_jobs",
            columns={
                "title": "title",
                "company": "company",
                "location": "location",
                "location_clean": "location_clean",
                "salary": "salary",
                "working_type": "working_type",
                "job_function": "job_function",
                "seniority": "seniority",
                "label": "label",
                "label_clean": "label_clean",
                "posted_time": "posted_date",
                "posted_hours_ago": "posted_hours_ago",
                "url": "url",
                "tags": "skills",
                "highlights": "highlights",
                "skill_categories": "skill_categories",
                "num_tags": "num_skills",
                "has_highlights": "has_highlights",
                "scraped_at": "scraped_at",
            },
            conflict_key="url",
            update_columns=("title", "company", "salary", "seniority", "label", "tags", "scraped_at"),
            json_columns=("tags", "highlights", "skill_categories"),
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


__all__ = ["ItviecSource"]
