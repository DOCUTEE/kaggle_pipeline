"""HTML → Job: parse thuần, KHÔNG cần browser → test offline được.

Cùng vai trò với `pipeline/sources/itviec/parser.py`.

Markup thật của topcv.vn (kiểm tra trực tiếp 2026-09-20):

    div.job-item-search-result[data-job-id]       ← card
      h3.title a[href=/viec-lam/<slug>/<id>.html] ← title + url
      span.company-name / a.company               ← công ty
      label.salary / label.title-salary           ← lương   ("Tới 33 triệu")
      span.city-text / a.address                  ← địa điểm
      label.address.label-update                  ← "Đăng 1 tuần trước"
      span.item-tag                               ← tag yêu cầu/kỹ năng
      label.tag-job.is-hot-job                    ← nhãn HOT
    ul.pagination  "1 / 55 trang"                 ← tổng số trang

Lưu ý: field nằm ở nhiều loại thẻ khác nhau (label/span/a/div) → tìm theo
**class** chứ không giới hạn thẻ, nếu không sẽ hụt field (đúng lỗi cũ: lương
nằm trong `<label class="salary">` nên `find("span"/"div")` bỏ sót).
"""

from __future__ import annotations

import re
from typing import Optional, Sequence

from bs4 import BeautifulSoup, Tag

from .client import BASE_URL
from .models import Job

#: Selector cho card job, theo thứ tự ưu tiên (mới → cũ).
CARD_SELECTORS: tuple[str, ...] = (".job-item-search-result",)

#: Fallback khi topcv đổi class (giữ để không vỡ hoàn toàn).
LEGACY_CARD_PATTERNS: tuple[tuple[str, dict], ...] = (
    ("find_all", {"name": "div", "class_": re.compile(r"job-list-search.*?item|job-item")}),
    ("find_all", {"name": "div", "class_": re.compile(r"job-card")}),
)

#: Selector từng field, theo thứ tự ưu tiên: markup MỚI trước, rồi tới các
#: biến thể cũ/generic để topcv đổi class lần nữa vẫn còn đường lùi.
FIELD_SELECTORS: dict[str, tuple[str, ...]] = {
    "company": (".company-name", "a.company", "[class*=company]", "[class*=employer]"),
    "salary": (".salary", ".title-salary", "[class*=salary]", "[class*=luong]"),
    "location": (".city-text", "a.address", "span.address", "[class*=location]", "[class*=city]"),
    "posted_date": (".label-update", "[class*=posted]", "[class*=date]", "[class*=time]"),
    "experience": (".exp", "[class*=experience]"),
    "level": (".level", "[class*=level]"),
    "deadline": (".deadline", "[class*=deadline]", "[class*=hạn]"),
}

#: Từ khoá nhận diện tin "gấp".
URGENT_KEYWORDS = ("urgent", "gấp", "khẩn")

#: Tag kinh nghiệm dạng "3 năm kinh nghiệm" → tách riêng khỏi skills.
_EXPERIENCE_RE = re.compile(r"(\d+)\s*năm", re.IGNORECASE)


def _text_of(card: Tag, selectors: Sequence[str]) -> str:
    """Lấy text của selector đầu tiên có nội dung."""
    for selector in selectors:
        el = card.select_one(selector)
        if el is not None:
            text = el.get_text(" ", strip=True)
            if text:
                return text
    return ""


def _absolute(href: str) -> str:
    if not href:
        return ""
    if href.startswith("/"):
        return BASE_URL + href
    return href if href.startswith("http") else ""


def select_job_cards(soup: BeautifulSoup) -> list[Tag]:
    """Tìm card job trong HTML trang listing (mới → cũ)."""
    for selector in CARD_SELECTORS:
        cards = soup.select(selector)
        if cards:
            return cards

    # Backup: div có data-job-id VÀ chứa tiêu đề (nút apply/ignore cũng có attr này)
    cards = [el for el in soup.find_all("div", attrs={"data-job-id": True}) if el.find("h3")]
    if cards:
        return cards

    for _, kwargs in LEGACY_CARD_PATTERNS:
        cards = soup.find_all(**kwargs)
        if cards:
            return cards
    return list(soup.select(".search-result .job, .job-list .job"))


def parse_job_card(card_html: str) -> Optional[Job]:
    """Parse 1 card job. Trả None nếu không có title (card rỗng/quảng cáo)."""
    soup = BeautifulSoup(card_html, "lxml")
    job = Job()

    card_el = soup.find(attrs={"data-job-id": True}) or soup.find(
        "div", class_=re.compile(r"job-item-search-result|job-list-search|job-item")
    )
    if card_el is not None:
        job_id = card_el.get("data-job-id", "") or card_el.get("data-id", "")
        if job_id:
            job.job_id = str(job_id)

    card: Tag = card_el if isinstance(card_el, Tag) else soup

    link = (
        card.select_one("h3.title a")
        or card.select_one("h3 a")
        or card.select_one("a[href*='/viec-lam/']")
        or card.select_one("a.title, a.job-name")
    )
    if link is not None:
        job.title = link.get_text(" ", strip=True)
        job.url = _absolute(link.get("href", ""))

    if not job.title:
        return None

    # job_id dự phòng: lấy từ URL dạng ...-<id>.html
    if not job.job_id and job.url:
        match = re.search(r"-(\d+)\.html", job.url)
        if match:
            job.job_id = match.group(1)

    company_el = card.select_one("a.company") or card.select_one(".company-name")
    if company_el is not None:
        job.company = company_el.get_text(" ", strip=True)
        href = company_el.get("href", "") if company_el.name == "a" else ""
        if href:
            job.company_url = _absolute(href)
    if not job.company:
        job.company = _text_of(card, FIELD_SELECTORS["company"])

    for field, selectors in FIELD_SELECTORS.items():
        if field == "company":
            continue
        setattr(job, field, _text_of(card, selectors))

    # skills: tag yêu cầu/kỹ năng; tag dạng "3 năm kinh nghiệm" tách sang experience
    tag_els = card.select(".item-tag")
    if not tag_els:
        # markup cũ: span.tag / span.skill (bỏ nhãn tuyển dụng .tag-job)
        tag_els = [
            el
            for el in card.select("[class*=tag], [class*=skill]")
            if "tag-job" not in " ".join(el.get("class", []))
        ]
    tags = [el.get_text(" ", strip=True) for el in tag_els]
    tags = [t for t in tags if t]
    skills: list[str] = []
    for tag in tags:
        if _EXPERIENCE_RE.search(tag) and not job.experience:
            job.experience = tag
            continue
        skills.append(tag)
    job.skills = skills or tags

    # nhãn HOT / URGENT
    label_text = " ".join(
        el.get_text(" ", strip=True) for el in card.select(".tag-job, .label, .badge")
    ).lower()
    job.is_hot = bool(card.select_one(".is-hot-job")) or "hot" in label_text
    job.is_urgent = any(kw in label_text for kw in URGENT_KEYWORDS)

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
    """Đọc tổng số trang (mặc định 1 nếu không thấy).

    topcv render dạng text `1 / 55 trang` (không có link `?page=`);
    vẫn giữ fallback cho link số / rel=next của markup cũ.
    """
    soup = BeautifulSoup(html, "lxml")

    pagination = soup.find("ul", class_=re.compile(r"pagination|paging"))
    if pagination:
        text = pagination.get_text(" ", strip=True)
        match = re.search(r"\d+\s*/\s*(\d+)", text)      # "1 / 55 trang"
        if match:
            return int(match.group(1))

        max_page = 1
        for link in pagination.find_all("a", class_=re.compile(r"page")):
            link_text = link.get_text(strip=True)
            if link_text.isdigit():
                max_page = max(max_page, int(link_text))
        if max_page > 1:
            return max_page

    next_link = soup.find("a", {"rel": "next"}) or soup.find("li", class_="next")
    if next_link:
        match = re.search(r"page=(\d+)", next_link.get("href", ""))
        if match:
            return int(match.group(1))

    return 1


__all__ = [
    "CARD_SELECTORS",
    "FIELD_SELECTORS",
    "parse_job_card",
    "parse_jobs",
    "parse_total_pages",
    "select_job_cards",
]
