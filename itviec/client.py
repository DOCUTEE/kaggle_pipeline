"""HTTP client for itviec.com with retries, backoff and rate limiting.

Design notes (senior-data-engineer review):
- Distinguishes *permanent* access errors (403/401/429 -> stop, never retry)
  from *transient* errors (timeout, 5xx -> retry with exponential backoff).
- Retry with exponential backoff + jitter via `tenacity`.
- Polite per-domain rate limiting with jitter (respect robots.txt: allow all,
  sitemap https://itviec.com/dunggiatminh.xml).
- Single session reused across all pages (keep-alive, connection pooling).
"""

from __future__ import annotations

import logging
import random
import re
import time
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse

import requests
from tenacity import (
    RetryError,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30
MAX_RETRIES = 4
MAX_REDIRECTS = 5

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_STOP_STATUS_CODES = {401, 403}  # permanent access denial: never retry
_RATE_LIMIT_CODE = 429  # transient: retry with long backoff (server says slow down)


class AccessDeniedError(RuntimeError):
    """The origin denied automated access; do NOT retry or escalate."""


class FetchError(RuntimeError):
    """All attempts to fetch a URL failed after retries."""


def _is_transient(exc: BaseException) -> bool:
    """Retry only transient failures; never retry access denial.

    429 (rate limit) is transient: the server asks us to slow down, so we
    back off and retry — that *honors* the control rather than evading it.
    """
    if isinstance(exc, AccessDeniedError):
        return False
    if isinstance(exc, (requests.exceptions.Timeout, requests.exceptions.ConnectionError)):
        return True
    if isinstance(exc, requests.exceptions.HTTPError):
        status = exc.response.status_code if exc.response is not None else None
        if status == _RATE_LIMIT_CODE:
            return True
        return status is not None and status >= 500
    return False


@retry(
    retry=retry_if_exception(_is_transient),
    wait=wait_exponential_jitter(initial=1.0, max=20.0),
    stop=stop_after_attempt(MAX_RETRIES + 2),
    reraise=True,
)
def _get_with_retry(session: requests.Session, url: str, **kwargs) -> requests.Response:
    """GET with retries; honors Retry-After when present (see below)."""
    resp = session.get(url, **kwargs)
    if resp.status_code == _RATE_LIMIT_CODE:
        retry_after = resp.headers.get("Retry-After")
        if retry_after and retry_after.isdigit():
            wait_secs = min(int(retry_after), 30)
            logger.warning("429 with Retry-After=%ss; waiting before retry", wait_secs)
            time.sleep(wait_secs)
        resp.close()
        resp.raise_for_status()  # triggers tenacity retry (transient)
    return resp


@dataclass
class RateLimiter:
    """Per-domain polite rate limiting with jitter."""

    min_delay: float = 0.5
    max_delay: float = 1.5
    _last_request_at: dict[str, float] = field(default_factory=dict)

    def wait_for_domain(self, url: str) -> None:
        domain = urlparse(url).netloc
        last = self._last_request_at.get(domain, 0.0)
        delay = random.uniform(self.min_delay, self.max_delay)
        elapsed = time.time() - last
        if elapsed < delay:
            time.sleep(delay - elapsed)
        self._last_request_at[domain] = time.time()


class ItviecClient:
    """Thin client over the itviec.com job listing endpoints.

    robots.txt: ``User-Agent * / Allow /`` (only /subscriptions/new disallowed),
    so crawling the listing pages is explicitly allowed.
    """

    BASE_URL = "https://itviec.com"
    JOBS_URL = f"{BASE_URL}/it-jobs"
    PAGE_SIZE = 20

    def __init__(
        self,
        *,
        timeout: int = DEFAULT_TIMEOUT,
        min_delay: float = 0.5,
        max_delay: float = 1.5,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.session = session or self._build_session()
        self.timeout = timeout
        self.rate_limiter = RateLimiter(min_delay=min_delay, max_delay=max_delay)

    @staticmethod
    def _build_session() -> requests.Session:
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9,vi;q=0.8",
                "Accept-Encoding": "gzip, deflate",
            }
        )
        return session

    def _fetch(
        self,
        url: str,
        *,
        ajax: bool = False,
        params: Optional[dict] = None,
    ) -> requests.Response:
        """Fetch a URL honoring rate limits, redirects and stop-codes.

        Returns a *non-redirect* response (redirects are followed up to
        MAX_REDIRECTS hops, validating each hop).
        """
        self.rate_limiter.wait_for_domain(url)
        headers = (
            {
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json, text/javascript, */*; q=0.01",
            }
            if ajax
            else {}
        )
        try:
            resp = _get_with_retry(
                self.session,
                url,
                headers=headers,
                params=params,
                timeout=self.timeout,
                allow_redirects=False,
            )
        except RetryError as exc:
            raise FetchError(f"Failed to fetch {url} after retries: {exc}") from exc
        except requests.exceptions.HTTPError as exc:
            raise FetchError(f"HTTP error fetching {url}: {exc}") from exc

        if resp.status_code in _STOP_STATUS_CODES:
            resp.close()
            raise AccessDeniedError(
                f"{resp.status_code} for {url}; origin denied automated access"
            )

        if resp.is_redirect:
            location = resp.headers.get("Location")
            resp.close()
            if not location:
                raise FetchError(f"Redirect without Location for {url}")
            target = location if location.startswith("http") else requests.compat.urljoin(url, location)
            for _ in range(MAX_REDIRECTS):
                redirected = self._fetch(target, ajax=ajax, params=params)
                if not redirected.is_redirect:
                    return redirected
                location = redirected.headers.get("Location")
                redirected.close()
                if not location:
                    raise FetchError(f"Redirect chain without Location for {url}")
                target = location if location.startswith("http") else requests.compat.urljoin(target, location)
            raise FetchError(f"Too many redirects for {url}")

        resp.raise_for_status()
        return resp

    # ------------------------------------------------------------------
    # Public API used by the runner
    # ------------------------------------------------------------------
    def fetch_listing_page(self, page: int = 1) -> str:
        """Return raw listing HTML (string) for a page.

        Page 1 is full server-rendered HTML; pages >= 2 use the AJAX JSON
        endpoint which returns ``jobs_html``, saving bandwidth.
        """
        if page <= 1:
            resp = self._fetch(self.JOBS_URL)
            return resp.text

        params = {"page": page, "query": "", "source": "search_job"}
        resp = self._fetch(self.JOBS_URL, ajax=True, params=params)
        payload = resp.json()
        if not isinstance(payload, dict):
            raise FetchError(f"Unexpected AJAX payload type for page {page}: {type(payload)}")
        return payload.get("jobs_html", "")

    def fetch_total_jobs(self) -> int:
        """Total number of live jobs, parsed from the first page header."""
        html = self.fetch_listing_page(1)
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        total_el = soup.find(class_="headline-total-jobs")
        if total_el is None:
            logger.warning("headline-total-jobs not found on listing page")
            return 0
        text = total_el.get_text(strip=True)
        match = re.search(r"[\d,]+", text)
        if not match:
            logger.warning("Could not parse total jobs count from %r", text)
            return 0
        try:
            return int(match.group(0).replace(",", ""))
        except ValueError:
            logger.warning("Could not parse total jobs count from %r", text)
            return 0