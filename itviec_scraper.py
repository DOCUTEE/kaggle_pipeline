#!/usr/bin/env python3
"""
ITviec.com Job Scraper
Scrapes all IT jobs from itviec.com/it-jobs with pagination support.
Saves results to CSV and JSON.
"""

import requests
from bs4 import BeautifulSoup
import json
import csv
import time
import random
import re
import os
from datetime import datetime
from pathlib import Path


BASE_URL = "https://itviec.com"
JOBS_URL = f"{BASE_URL}/it-jobs"
OUTPUT_DIR = Path("data/itviec")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,vi;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}

AJAX_HEADERS = {
    **HEADERS,
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01",
}


def _root_attr(soup: BeautifulSoup, attr: str, default=""):
    """Get an attribute from the root element of a parsed fragment."""
    root = soup.find(True)  # first element
    if root is None:
        return default
    return root.get(attr, default)


def parse_job_card(card_html: str, page_num: int) -> dict | None:
    """Parse a single job card HTML into a structured dict."""
    soup = BeautifulSoup(card_html, "html.parser")

    job = {
        "job_key": "",
        "title": "",
        "url": "",
        "company": "",
        "salary": "",
        "job_function": "",   # e.g. "Site Reliability Engineer (SRE)"
        "working_type": "",   # Remote/Hybrid/At office
        "location": "",
        "tags": [],
        "posted_time": "",
        "label": "",          # HOT / SUPER HOT / NORMAL
        "highlights": [],
        "page": page_num,
    }

    # Job key from root div's data attribute
    job["job_key"] = _root_attr(soup, "data-job-key")

    # Title and URL (inside h3)
    h3 = soup.find("h3")
    if h3:
        a_tag = h3.find("a")
        if a_tag:
            job["title"] = a_tag.get_text(strip=True)
            href = a_tag.get("href", "")
            if href:
                if href.startswith("/"):
                    job["url"] = BASE_URL + href.split("?")[0]
                elif href.startswith("http"):
                    job["url"] = href.split("?")[0]

    # Company name: first standalone text-rich-grey element that is not
    # the working type, location, or a tag.
    company_candidates = soup.find_all(class_="text-rich-grey")
    for c in company_candidates:
        classes = " ".join(c.get("class", []))
        if "itag" in classes:
            continue
        text = c.get_text(strip=True)
        if text:
            job["company"] = text
            break

    # Salary (login-gated on the listing page)
    salary_el = soup.find(class_="sign-in-view-salary")
    if salary_el:
        job["salary"] = salary_el.get_text(strip=True)

    # Working type: Remote / Hybrid / At office
    for el in soup.find_all(class_="flex-shrink-0"):
        text = el.get_text(strip=True)
        if text in ("Remote", "Hybrid", "At office", "Office"):
            job["working_type"] = text
            break

    # Location: text-nowrap element whose value is a city name
    for el in soup.find_all(class_=re.compile(r"text-nowrap")):
        text = el.get_text(strip=True)
        if text and text not in ("Remote", "Hybrid", "At office", "Office"):
            job["location"] = text
            break

    # Tags/skills
    tag_els = soup.find_all(class_=re.compile(r"itag-light"))
    job["tags"] = [t.get_text(strip=True) for t in tag_els if t.get_text(strip=True)]

    # Posted time
    posted_el = soup.find(class_="small-text")
    if posted_el:
        job["posted_time"] = (
            posted_el.get_text(strip=True).replace("Posted", "").strip()
        )

    # Label: SUPER HOT / HOT
    ilabel = soup.find(class_=re.compile(r"ilabel"))
    if ilabel:
        label_text = ilabel.get_text(strip=True).upper()
        if "SUPER HOT" in label_text:
            job["label"] = "SUPER HOT"
        elif "HOT" in label_text:
            job["label"] = "HOT"

    # Highlights (bullet points)
    highlight_els = soup.find_all(class_="imb-1")
    job["highlights"] = [
        h.get_text(strip=True) for h in highlight_els if h.get_text(strip=True)
    ]

    # Job function/subtitle: the multiline-ellipsis small text under the company
    subtitle = soup.find(class_=re.compile(r"text-decoration-dot-underline|text-truncate"))
    if subtitle:
        text = subtitle.get_text(strip=True)
        if text and text != job.get("title", ""):
            job["job_function"] = text

    return job if job["title"] else None


def get_total_jobs(session: requests.Session) -> int:
    """Get the total number of jobs from the first page."""
    resp = session.get(JOBS_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    total_el = soup.find(class_="headline-total-jobs")
    if total_el:
        text = total_el.get_text(strip=True)
        match = re.search(r"(\d+)", text)
        if match:
            return int(match.group(1))
    return 0


def scrape_page(session: requests.Session, page: int) -> list[dict]:
    """Scrape a single page of jobs."""
    if page == 1:
        # First page: fetch full HTML
        resp = session.get(JOBS_URL, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        cards = soup.find_all(class_="job-card")
    else:
        # AJAX pagination
        params = {"page": page, "query": "", "source": "search_job"}
        resp = session.get(JOBS_URL, params=params, headers=AJAX_HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        html = data.get("jobs_html", "")
        soup = BeautifulSoup(html, "html.parser")
        cards = soup.find_all(class_="job-card")

    jobs = []
    for card in cards:
        job = parse_job_card(str(card), page)
        if job:
            jobs.append(job)

    return jobs


def scrape_all_jobs():
    """Scrape all jobs from itviec.com."""
    session = requests.Session()
    session.headers.update(HEADERS)

    # Get total jobs
    total = get_total_jobs(session)
    total_pages = (total + 19) // 20  # 20 per page
    print(f"Total jobs: {total}, pages to scrape: {total_pages}")

    all_jobs = []
    failed_pages = []

    for page in range(1, total_pages + 1):
        try:
            jobs = scrape_page(session, page)
            all_jobs.extend(jobs)
            print(f"Page {page}/{total_pages}: {len(jobs)} jobs (total: {len(all_jobs)})")

            # Polite delay with jitter
            if page < total_pages:
                delay = random.uniform(0.5, 1.5)
                time.sleep(delay)

        except Exception as e:
            print(f"Page {page} failed: {e}")
            failed_pages.append(page)
            # Retry once after longer delay
            time.sleep(3)
            try:
                jobs = scrape_page(session, page)
                all_jobs.extend(jobs)
                print(f"Page {page} RETRY OK: {len(jobs)} jobs (total: {len(all_jobs)})")
            except Exception as e2:
                print(f"Page {page} RETRY also failed: {e2}")

    # Deduplicate by job_key
    seen = set()
    unique_jobs = []
    for job in all_jobs:
        key = job["job_key"] or job["url"]
        if key and key not in seen:
            seen.add(key)
            unique_jobs.append(job)
        elif not key:
            unique_jobs.append(job)

    print(f"\nScraping complete: {len(unique_jobs)} unique jobs (from {len(all_jobs)} total)")
    if failed_pages:
        print(f"Failed pages: {failed_pages}")

    return unique_jobs


def save_results(jobs: list[dict]):
    """Save results to CSV and JSON."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Save JSON
    json_path = OUTPUT_DIR / f"itviec_jobs_{timestamp}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "scraped_at": datetime.now().isoformat(),
                "total_jobs": len(jobs),
                "jobs": jobs,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"Saved JSON: {json_path}")

    # Save CSV
    csv_path = OUTPUT_DIR / f"itviec_jobs_{timestamp}.csv"
    if jobs:
        fieldnames = [
            "job_key",
            "title",
            "company",
            "salary",
            "job_function",
            "working_type",
            "location",
            "tags",
            "posted_time",
            "label",
            "highlights",
            "url",
            "page",
        ]
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for job in jobs:
                # Convert lists to strings for CSV
                row = {**job}
                row["tags"] = " | ".join(row.get("tags", []))
                row["highlights"] = " | ".join(row.get("highlights", []))
                writer.writerow(row)
        print(f"Saved CSV: {csv_path}")

    # Also save a latest symlink/copy
    latest_json = OUTPUT_DIR / "itviec_jobs_latest.json"
    latest_csv = OUTPUT_DIR / "itviec_jobs_latest.csv"

    import shutil
    shutil.copy2(json_path, latest_json)
    shutil.copy2(csv_path, latest_csv)
    print(f"Updated latest: {latest_json}, {latest_csv}")


if __name__ == "__main__":
    print(f"Starting ITviec job scraper at {datetime.now().isoformat()}")
    print("=" * 60)

    jobs = scrape_all_jobs()

    if jobs:
        save_results(jobs)
        print("=" * 60)
        print(f"Done! Scraped {len(jobs)} jobs.")

        # Quick stats
        companies = set(j["company"] for j in jobs if j["company"])
        locations = set(j["location"] for j in jobs if j["location"])
        print(f"Unique companies: {len(companies)}")
        print(f"Locations: {locations}")
    else:
        print("No jobs scraped!")
