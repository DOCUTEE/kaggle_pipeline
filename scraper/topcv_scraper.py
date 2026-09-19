#!/usr/bin/env python3
"""
TopCV Job Scraper
Scrapes IT/Công nghệ thông tin jobs from topcv.vn using Playwright (Cloudflare bypass).

Chỉ làm 1 việc: scrape → trả `list[Job]`. Việc ghi file/process/publish do
pipeline lo (`pipeline/sources/topcv.py` + `pipeline/core/`).
Chạy: `python -m pipeline run topcv`.
"""

import time
import random
import re
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, field

from playwright.sync_api import sync_playwright, Page, Browser
from bs4 import BeautifulSoup


BASE_URL = "https://www.topcv.vn"
SEARCH_URL = "https://www.topcv.vn/tim-viec-lam-cong-nghe-thong-tin-cr257"

# Default query params
DEFAULT_PARAMS = {
    "type_keyword": "1",
    "sba": "1",
    "category_family": "r257",
}


@dataclass
class Job:
    job_id: str = ""
    title: str = ""
    url: str = ""
    company: str = ""
    company_url: str = ""
    salary: str = ""
    location: str = ""
    experience: str = ""
    level: str = ""
    job_type: str = ""
    category: str = ""
    skills: list = field(default_factory=list)
    posted_date: str = ""
    deadline: str = ""
    is_hot: bool = False
    is_urgent: bool = False
    scrape_date: str = ""

    def __post_init__(self):
        if not self.scrape_date:
            self.scrape_date = datetime.now().strftime("%Y-%m-%d")


class TopCVScraper:
    """Scraper for topcv.vn job listings."""

    def __init__(self, headless: bool = True):
        self.headless = headless
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None

    def _build_url(self, page: int = 1, keyword: str = "") -> str:
        """Build search URL with parameters."""
        params = {**DEFAULT_PARAMS}
        if keyword:
            params["q"] = keyword
        if page > 1:
            params["page"] = str(page)

        param_str = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{SEARCH_URL}?{param_str}"

    def start_browser(self):
        """Launch Playwright browser."""
        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.launch(
            headless=self.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        context = self.browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="vi-VN",
        )
        # Remove webdriver flag
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        """)
        self.page = context.new_page()

    def stop_browser(self):
        """Close browser."""
        if self.browser:
            self.browser.close()
        if hasattr(self, 'pw') and self.pw:
            self.pw.stop()

    def _wait_for_cloudflare(self, timeout: int = 15):
        """Wait for Cloudflare challenge to complete."""
        start = time.time()
        while time.time() - start < timeout:
            # Check if we're past Cloudflare
            title = self.page.title()
            if "cloudflare" not in title.lower() and "checking" not in title.lower():
                return True
            # Check for challenge elements
            challenge = self.page.query_selector("#challenge-running, #challenge-form, .cf-browser-verification")
            if not challenge:
                return True
            time.sleep(1)
        return False

    def parse_job_card(self, card_html: str) -> Optional[Job]:
        """Parse a single job card from HTML."""
        soup = BeautifulSoup(card_html, "html.parser")

        job = Job()

        # Job ID from data attribute or URL
        card_el = soup.find("div", class_=re.compile(r"job-list-search|job-item"))
        if card_el:
            job_id = card_el.get("data-job-id", "") or card_el.get("data-id", "")
            if job_id:
                job.job_id = str(job_id)

        # Title and URL
        title_el = soup.find("h3") or soup.find("a", class_=re.compile(r"title|job-name"))
        if title_el:
            a_tag = title_el.find("a") if title_el.name != "a" else title_el
            if a_tag:
                job.title = a_tag.get_text(strip=True)
                href = a_tag.get("href", "")
                if href:
                    if href.startswith("/"):
                        job.url = BASE_URL + href
                    elif href.startswith("http"):
                        job.url = href

        if not job.title:
            return None

        # Extract job_id from URL if not found
        if not job.job_id and job.url:
            match = re.search(r"-(\d+)\.html", job.url)
            if match:
                job.job_id = match.group(1)

        # Company
        company_el = soup.find("a", class_=re.compile(r"company|employer")) or \
                      soup.find("div", class_=re.compile(r"company|employer"))
        if company_el:
            job.company = company_el.get_text(strip=True)
            href = company_el.get("href", "")
            if href and href.startswith("/"):
                job.company_url = BASE_URL + href

        # Salary
        salary_el = soup.find("span", class_=re.compile(r"salary|luong")) or \
                     soup.find("div", class_=re.compile(r"salary|luong"))
        if salary_el:
            job.salary = salary_el.get_text(strip=True)

        # Location
        location_el = soup.find("span", class_=re.compile(r"location|address|city")) or \
                       soup.find("div", class_=re.compile(r"location|address"))
        if location_el:
            job.location = location_el.get_text(strip=True)

        # Experience
        exp_el = soup.find("span", class_=re.compile(r"experience|exp"))
        if exp_el:
            job.experience = exp_el.get_text(strip=True)

        # Level
        level_el = soup.find("span", class_=re.compile(r"level|rank"))
        if level_el:
            job.level = level_el.get_text(strip=True)

        # Skills/Tags
        skill_els = soup.find_all("span", class_=re.compile(r"tag|skill|label"))
        job.skills = [s.get_text(strip=True) for s in skill_els if s.get_text(strip=True)]

        # Posted date
        date_el = soup.find("span", class_=re.compile(r"time|date|posted"))
        if date_el:
            job.posted_date = date_el.get_text(strip=True)

        # Deadline
        deadline_el = soup.find("span", class_=re.compile(r"deadline|hạn"))
        if deadline_el:
            job.deadline = deadline_el.get_text(strip=True)

        # Hot/Urgent badges
        badge_els = soup.find_all("span", class_=re.compile(r"badge|hot|urgent|new"))
        for badge in badge_els:
            text = badge.get_text(strip=True).lower()
            if "hot" in text:
                job.is_hot = True
            if "urgent" in text or "khẩn" in text:
                job.is_urgent = True

        return job

    def scrape_page(self, page_num: int = 1) -> list[Job]:
        """Scrape a single page of job listings."""
        url = self._build_url(page=page_num)
        print(f"  Fetching page {page_num}: {url}")

        self.page.goto(url, wait_until="domcontentloaded", timeout=60000)

        # Wait for Cloudflare if needed
        self._wait_for_cloudflare()

        # Wait for job list to load
        try:
            self.page.wait_for_selector(
                ".job-list-search, .job-item, .search-result, [class*='job-card']",
                timeout=15000,
            )
        except Exception:
            print(f"  Warning: Job list selector not found on page {page_num}")

        # Get page HTML
        html = self.page.content()
        soup = BeautifulSoup(html, "lxml")

        # Try multiple selectors for job cards
        cards = (
            soup.find_all("div", class_=re.compile(r"job-list-search.*?item|job-item")) or
            soup.find_all("div", class_=re.compile(r"job-card")) or
            soup.find_all("div", {"data-job-id": True}) or
            soup.select(".search-result .job, .job-list .job")
        )

        jobs = []
        for card in cards:
            job = self.parse_job_card(str(card))
            if job and job.title:
                jobs.append(job)

        return jobs

    def get_total_pages(self) -> int:
        """Get total number of pages from pagination."""
        html = self.page.content()
        soup = BeautifulSoup(html, "lxml")

        # Look for pagination
        pagination = soup.find("ul", class_=re.compile(r"pagination|paging"))
        if pagination:
            page_links = pagination.find_all("a", class_=re.compile(r"page"))
            max_page = 1
            for link in page_links:
                text = link.get_text(strip=True)
                if text.isdigit():
                    max_page = max(max_page, int(text))
            return max_page

        # Try next page link
        next_link = soup.find("a", {"rel": "next"}) or soup.find("li", class_="next")
        if next_link:
            href = next_link.get("href", "")
            match = re.search(r"page=(\d+)", href)
            if match:
                return int(match.group(1))

        return 1

    def scrape_all(self, max_pages: int = 50) -> list[Job]:
        """Scrape all pages of job listings."""
        print("Starting TopCV job scraper...")
        print(f"Target: {SEARCH_URL}")
        print("=" * 60)

        self.start_browser()

        try:
            # First page to get total pages
            print("Loading first page...")
            first_jobs = self.scrape_page(1)
            total_pages = self.get_total_pages()
            total_pages = min(total_pages, max_pages)  # Cap at max_pages

            print(f"Found {len(first_jobs)} jobs on page 1")
            print(f"Total pages detected: {total_pages}")

            all_jobs = list(first_jobs)

            # Scrape remaining pages
            for page_num in range(2, total_pages + 1):
                # Random delay between pages
                delay = random.uniform(1.5, 3.0)
                time.sleep(delay)

                try:
                    jobs = self.scrape_page(page_num)
                    all_jobs.extend(jobs)
                    print(f"Page {page_num}/{total_pages}: {len(jobs)} jobs (total: {len(all_jobs)})")
                except Exception as e:
                    print(f"Page {page_num} failed: {e}")
                    # Retry once
                    time.sleep(5)
                    try:
                        jobs = self.scrape_page(page_num)
                        all_jobs.extend(jobs)
                        print(f"Page {page_num} RETRY OK: {len(jobs)} jobs")
                    except Exception as e2:
                        print(f"Page {page_num} RETRY also failed: {e2}")

            # Deduplicate
            seen = set()
            unique_jobs = []
            for job in all_jobs:
                key = job.job_id or job.url
                if key and key not in seen:
                    seen.add(key)
                    unique_jobs.append(job)

            print(f"\nScraping complete: {len(unique_jobs)} unique jobs")
            return unique_jobs

        finally:
            self.stop_browser()
