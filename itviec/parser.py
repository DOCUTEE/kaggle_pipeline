"""HTML parser for itviec.com job cards.

Separated from fetching so it can be unit-tested against HTML fixtures
and reused across pages. When the site changes markup, parsing fails
loudly (``ParsingQualityError`` when emptiness threshold exceeded) instead
of silently producing a file full of empty fields.
"""

from __future__ import annotations

import logging
import re
from typing import Iterable

from bs4 import BeautifulSoup, Tag

from itviec.models import Job, JobLabel, WorkingType

logger = logging.getLogger(__name__)

CARD_CLASS = "job-card"

# Fields whose emptiness indicates a broken parser (markup changed).
# Missing VALUES (e.g. salary gated behind login) are expected and excluded.
_REQUIRED_FIELDS = ("title", "company", "url", "location")

# Concurrent working types shown on cards.
_WORKING_TYPES = {wt.value for wt in WorkingType if wt.value}

_EMPTY_WORKING_TYPES = _WORKING_TYPES | {"Office"}

_WORKING_TYPE_CLASS_RE = re.compile(r"flex-shrink-0")
_LOCATION_CLASS_RE = re.compile(r"text-nowrap")
_TAG_CLASS_RE = re.compile(r"itag-light")
_LABEL_CLASS_RE = re.compile(r"ilabel")
_HIGHLIGHT_CLASS_RE = re.compile(r"imb-1")
_SUBTITLE_CLASS_RE = re.compile(r"text-decoration-dot-underline|text-truncate")
_COMPANY_CLASS = "text-rich-grey"


def _text(el: Tag | None) -> str:
    if el is None:
        return ""
    return el.get_text(strip=True)


def _root_attr(soup: BeautifulSoup, attr: str) -> str:
    root = soup.find(True)
    if root is None:
        return ""
    value = root.get(attr, "")
    return value if isinstance(value, str) else ""


BASE_URL = "https://itviec.com"


def _absolute_url(href: str) -> str:
    """Make a site-relative job URL absolute (strips tracking params)."""
    if href.startswith("http"):
        return href.split("?")[0]
    if href.startswith("/"):
        return BASE_URL + href.split("?")[0]
    return ""


def parse_card(card: Tag, *, page: int, scraped_at: str) -> Job:
    """Parse one job-card element into a validated Job."""
    title = ""
    url = ""

    h3 = card.find("h3")
    if h3:
        a_tag = h3.find("a")
        if a_tag:
            title = _text(a_tag)
            url = _absolute_url(a_tag.get("href", ""))

    # Company: first non-tag text-rich-grey element
    company = ""
    for c in card.find_all(class_=_COMPANY_CLASS):
        classes = " ".join(c.get("class", []))
        if "itag" in classes:
            continue
        company = _text(c)
        if company:
            break

    # Salary: login-gated on the listing page
    salary_el = card.find(class_="sign-in-view-salary")
    salary = _text(salary_el)

    # Working type
    working_type = WorkingType.UNKNOWN
    for el in card.find_all(class_=_WORKING_TYPE_CLASS_RE):
        text = _text(el)
        if text in _WORKING_TYPES:
            working_type = WorkingType(text)
            break

    # Location
    location = ""
    for el in card.find_all(class_=_LOCATION_CLASS_RE):
        text = _text(el)
        if text and text not in _EMPTY_WORKING_TYPES:
            location = text
            break

    # Tags
    tags = [_text(t) for t in card.find_all(class_=_TAG_CLASS_RE)]
    tags = [t for t in tags if t]

    # Posted time
    posted_el = card.find(class_="small-text")
    posted = _text(posted_el).replace("Posted", "").strip()

    # Label
    label = JobLabel.NONE
    ilabel = card.find(class_=_LABEL_CLASS_RE)
    if ilabel:
        label_text = _text(ilabel).upper()
        if "SUPER HOT" in label_text:
            label = JobLabel.SUPER_HOT
        elif "HOT" in label_text:
            label = JobLabel.HOT

    # Highlights
    highlights = [_text(h) for h in card.find_all(class_=_HIGHLIGHT_CLASS_RE)]
    highlights = [h for h in highlights if h]

    # Job function (subtitle)
    job_function = ""
    subtitle = card.find(class_=_SUBTITLE_CLASS_RE)
    if subtitle:
        text = _text(subtitle)
        if text and text != title:
            job_function = text

    job = Job(
        job_key=_root_attr(BeautifulSoup(str(card), "html.parser"), "data-job-key"),
        title=title,
        url=url,
        company=company,
        salary=salary,
        job_function=job_function,
        working_type=working_type,
        location=location,
        tags=tags,
        posted_time=posted,
        label=label,
        highlights=highlights,
        page=page,
        scraped_at=scraped_at,
    )
    return job


def parse_page(html: str, *, page: int, scraped_at: str, fail_threshold: float = 0.5) -> list[Job]:
    """Parse all job cards from a listing page's HTML.

    ``fail_threshold``: if the fraction of cards with any required field
    empty exceeds this, raise ParsingQualityError (markup likely changed).
    """
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.find_all(class_=CARD_CLASS)
    jobs = [parse_card(c, page=page, scraped_at=scraped_at) for c in cards]

    if jobs:
        bad = sum(1 for j in jobs if any(not getattr(j, f) for f in _REQUIRED_FIELDS))
        ratio = bad / len(jobs)
        if ratio > fail_threshold:
            raise ParsingQualityError(
                f"Parsing quality dropped: {bad}/{len(jobs)} cards missing required fields "
                f"({ratio:.0%} > {fail_threshold:.0%}) - site markup may have changed"
            )
    return jobs


class ParsingQualityError(RuntimeError):
    """Listing markup likely changed; refuse to emit garbage data."""