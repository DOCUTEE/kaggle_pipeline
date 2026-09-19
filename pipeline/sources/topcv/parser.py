"""HTML → Job: parse thuần, KHÔNG cần browser → test offline được.

Cùng vai trò với `pipeline/sources/itviec/parser.py`. TopCV render bằng
Playwright nên ở đây chỉ nhận HTML đã có sẵn.

Lưu ý: topcv.vn đổi class khá thường xuyên → mỗi field thử nhiều selector,
field nào không khớp thì để rỗng thay vì làm hỏng cả card.
"""

from __future__ import annotations

import re
from typing import Optional

from bs4 import BeautifulSoup, Tag

from .client import BASE_URL
from .models import Job

#: Các kiểu card job đã gặp; thử lần lượt cho tới khi có kết quả.
CARD_PATTERNS: tuple[tuple[str, dict], ...] = (
    ("find_all", {"name": "div", "class_": re.compile(r"job-list-search.*?item|job-item")}),
    ("find_all", {"name": "div", "class_": re.compile(r"job-card")}),
    ("find_all", {"name": "div", "attrs": {"data-job-id": True}}),
)


def select_job_cards(soup: BeautifulSoup) -> list[Tag]:
    """Tìm card job trong HTML trang listing (nhiều fallback selector)."""
    cards: list[Tag] = []
    for _, kwargs in CARD_PATTERNS:
        cards = soup.find_all(**kwargs)
        if cards:
            return cards
    return list(soup.select(".search-result .job, .job-list .job"))


def parse_job_card(card_html: str) -> Optional[Job]:
    """Parse 1 card job. Trả None nếu không có title (card rỗng/quảng cáo)."""
    soup = BeautifulSoup(card_html, "html.parser")
    job = Job()

    # Job ID từ data attribute
    card_el = soup.find("div", class_=re.compile(r"job-list-search|job-item"))
    if card_el:
        job_id = card_el.get("data-job-id", "") or card_el.get("data-id", "")
        if job_id:
            job.job_id = str(job_id)

    # Title + URL
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

    # Fallback: lấy job_id từ URL dạng ...-123456.html
    if not job.job_id and job.url:
        match = re.search(r"-(\d+)\.html", job.url)
        if match:
            job.job_id = match.group(1)

    company_el = soup.find("a", class_=re.compile(r"company|employer")) or \
        soup.find("div", class_=re.compile(r"company|employer"))
    if company_el:
        job.company = company_el.get_text(strip=True)
        href = company_el.get("href", "")
        if href and href.startswith("/"):
            job.company_url = BASE_URL + href

    salary_el = soup.find("span", class_=re.compile(r"salary|luong")) or \
        soup.find("div", class_=re.compile(r"salary|luong"))
    if salary_el:
        job.salary = salary_el.get_text(strip=True)

    location_el = soup.find("span", class_=re.compile(r"location|address|city")) or \
        soup.find("div", class_=re.compile(r"location|address"))
    if location_el:
        job.location = location_el.get_text(strip=True)

    exp_el = soup.find("span", class_=re.compile(r"experience|exp"))
    if exp_el:
        job.experience = exp_el.get_text(strip=True)

    level_el = soup.find("span", class_=re.compile(r"level|rank"))
    if level_el:
        job.level = level_el.get_text(strip=True)

    skill_els = soup.find_all("span", class_=re.compile(r"tag|skill|label"))
    job.skills = [s.get_text(strip=True) for s in skill_els if s.get_text(strip=True)]

    date_el = soup.find("span", class_=re.compile(r"time|date|posted"))
    if date_el:
        job.posted_date = date_el.get_text(strip=True)

    deadline_el = soup.find("span", class_=re.compile(r"deadline|hạn"))
    if deadline_el:
        job.deadline = deadline_el.get_text(strip=True)

    badge_els = soup.find_all("span", class_=re.compile(r"badge|hot|urgent|new"))
    for badge in badge_els:
        text = badge.get_text(strip=True).lower()
        if "hot" in text:
            job.is_hot = True
        if "urgent" in text or "khẩn" in text:
            job.is_urgent = True

    return job


def parse_jobs(html: str) -> list[Job]:
    """Parse toàn bộ trang listing → danh sách Job có title."""
    soup = BeautifulSoup(html, "lxml")
    jobs: list[Job] = []
    for card in select_job_cards(soup):
        job = parse_job_card(str(card))
        if job and job.title:
            jobs.append(job)
    return jobs


def parse_total_pages(html: str) -> int:
    """Đọc số trang từ pagination (mặc định 1 nếu không thấy)."""
    soup = BeautifulSoup(html, "lxml")

    pagination = soup.find("ul", class_=re.compile(r"pagination|paging"))
    if pagination:
        max_page = 1
        for link in pagination.find_all("a", class_=re.compile(r"page")):
            text = link.get_text(strip=True)
            if text.isdigit():
                max_page = max(max_page, int(text))
        return max_page

    next_link = soup.find("a", {"rel": "next"}) or soup.find("li", class_="next")
    if next_link:
        match = re.search(r"page=(\d+)", next_link.get("href", ""))
        if match:
            return int(match.group(1))

    return 1


__all__ = ["parse_job_card", "parse_jobs", "parse_total_pages", "select_job_cards"]
