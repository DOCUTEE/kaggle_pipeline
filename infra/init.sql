-- Schema for kaggle_pipeline job data

CREATE TABLE IF NOT EXISTS itviec_jobs (
    id              SERIAL PRIMARY KEY,
    title           TEXT NOT NULL,
    company         TEXT NOT NULL,
    location        TEXT,
    location_clean  TEXT,
    salary          TEXT,
    working_type    TEXT,
    job_function    TEXT,
    seniority       TEXT,
    label           TEXT,
    label_clean     TEXT,
    posted_time     TEXT,
    posted_hours_ago FLOAT,
    url             TEXT,
    tags            JSONB DEFAULT '[]'::jsonb,
    highlights      JSONB DEFAULT '[]'::jsonb,
    skill_categories JSONB DEFAULT '[]'::jsonb,
    num_tags        INT DEFAULT 0,
    has_highlights  BOOLEAN DEFAULT FALSE,
    scraped_at      TIMESTAMPTZ,
    loaded_at       TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (url)  -- prevent duplicates by URL
);

CREATE TABLE IF NOT EXISTS topcv_jobs (
    id              SERIAL PRIMARY KEY,
    job_id          TEXT UNIQUE,
    title           TEXT NOT NULL,
    company         TEXT,
    salary          TEXT,
    location        TEXT,
    experience      TEXT,
    level           TEXT,
    skills          TEXT,
    url             TEXT,
    is_hot          BOOLEAN DEFAULT FALSE,
    posted_date     TEXT,
    scrape_date     TEXT,
    loaded_at       TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_itviec_location ON itviec_jobs(location_clean);
CREATE INDEX IF NOT EXISTS idx_itviec_seniority ON itviec_jobs(seniority);
CREATE INDEX IF NOT EXISTS idx_itviec_company ON itviec_jobs(company);
CREATE INDEX IF NOT EXISTS idx_itviec_scraped ON itviec_jobs(scraped_at);
CREATE INDEX IF NOT EXISTS idx_topcv_location ON topcv_jobs(location);
CREATE INDEX IF NOT EXISTS idx_topcv_company ON topcv_jobs(company);

-- Views for dashboard queries
CREATE OR REPLACE VIEW v_itviec_stats AS
SELECT
    location_clean,
    seniority,
    working_type,
    company,
    label_clean,
    COUNT(*) as job_count,
    COUNT(DISTINCT company) as company_count
FROM itviec_jobs
GROUP BY location_clean, seniority, working_type, company, label_clean;

CREATE OR REPLACE VIEW v_skill_stats AS
SELECT
    jsonb_array_elements_text(tags) as skill,
    COUNT(*) as demand_count,
    seniority,
    location_clean
FROM itviec_jobs
WHERE jsonb_array_length(tags) > 0
GROUP BY skill, seniority, location_clean;

CREATE OR REPLACE VIEW v_daily_counts AS
SELECT
    DATE(scraped_at) as scrape_date,
    COUNT(*) as total_jobs,
    COUNT(DISTINCT company) as companies,
    location_clean
FROM itviec_jobs
WHERE scraped_at IS NOT NULL
GROUP BY DATE(scraped_at), location_clean
ORDER BY scrape_date DESC;

-- ─── arXiv papers (PDF file -> MinIO, metadata -> Postgres) ─────────────────
CREATE TABLE IF NOT EXISTS arxiv_papers (
    id               SERIAL PRIMARY KEY,
    arxiv_id         TEXT UNIQUE NOT NULL,   -- vd "2609.19146v1"
    title            TEXT NOT NULL,
    authors          TEXT,                   -- join bằng "; "
    abstract         TEXT,
    categories       TEXT,                   -- join bằng ";"
    primary_category TEXT,
    published        TIMESTAMPTZ,
    updated          TIMESTAMPTZ,
    pdf_url          TEXT,
    pdf_local        TEXT,                   -- đường dẫn file local
    minio_key        TEXT,                   -- key trong bucket (rỗng nếu fallback local)
    pdf_location     TEXT,                   -- "s3://bucket/key" hoặc "file://..."
    comment          TEXT,
    journal_ref      TEXT,
    doi              TEXT,
    scrape_date      TEXT,
    query            TEXT,
    loaded_at        TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_arxiv_category ON arxiv_papers(primary_category);
CREATE INDEX IF NOT EXISTS idx_arxiv_published ON arxiv_papers(published);
CREATE INDEX IF NOT EXISTS idx_arxiv_query ON arxiv_papers(query);
