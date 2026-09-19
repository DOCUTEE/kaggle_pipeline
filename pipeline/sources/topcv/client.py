"""Playwright client cho TopCV — vòng đời browser + truy cập trang (I/O thuần).

Tách khỏi parser để:
- phần parse HTML test được offline (không cần browser),
- phần điều khiển browser chỉ còn 1 chỗ (dễ thay khi Cloudflare đổi).

`playwright` được import **lazy** trong `start()` nên module này (và parser)
import được cả khi chưa cài browser.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:  # pragma: no cover - chỉ để type checker hiểu
    from playwright.sync_api import Browser, Page

BASE_URL = "https://www.topcv.vn"
SEARCH_URL = "https://www.topcv.vn/tim-viec-lam-cong-nghe-thong-tin-cr257"

#: Query params mặc định cho trang IT/Công nghệ thông tin.
DEFAULT_PARAMS = {
    "type_keyword": "1",
    "sba": "1",
    "category_family": "r257",
}

#: Selector chờ danh sách job render xong.
JOB_LIST_SELECTOR = ".job-list-search, .job-item, .search-result, [class*='job-card']"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def build_search_url(page: int = 1, keyword: str = "") -> str:
    """Tạo URL trang tìm việc (page 1 = không thêm tham số page)."""
    params = {**DEFAULT_PARAMS}
    if keyword:
        params["q"] = keyword
    if page > 1:
        params["page"] = str(page)
    param_str = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{SEARCH_URL}?{param_str}"


class TopCvBrowser:
    """Bọc Playwright chromium: mở trang, chờ Cloudflare, trả HTML."""

    def __init__(self, headless: bool = True) -> None:
        self.headless = headless
        self._pw = None
        self.browser: Optional["Browser"] = None
        self.page: Optional["Page"] = None

    # cho phép `with TopCvBrowser() as browser:` — tự đóng kể cả khi lỗi
    def __enter__(self) -> "TopCvBrowser":
        self.start()
        return self

    def __exit__(self, *exc_info) -> None:
        self.stop()

    def start(self) -> None:
        """Khởi động browser (stealth nhẹ để qua Cloudflare)."""
        from playwright.sync_api import sync_playwright  # lazy: không cần playwright khi import

        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.launch(
            headless=self.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        context = self.browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=USER_AGENT,
            locale="vi-VN",
        )
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
        self.page = context.new_page()

    def stop(self) -> None:
        """Đóng browser + playwright (gọi được nhiều lần)."""
        if self.browser:
            self.browser.close()
            self.browser = None
        if self._pw:
            self._pw.stop()
            self._pw = None
        self.page = None

    def open(self, url: str, *, timeout_ms: int = 60000) -> None:
        assert self.page is not None, "TopCvBrowser chưa start()"
        self.page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

    def wait_for_cloudflare(self, timeout_s: int = 15) -> bool:
        """Chờ challenge Cloudflare xong. Trả False nếu quá hạn."""
        assert self.page is not None, "TopCvBrowser chưa start()"
        start = time.time()
        while time.time() - start < timeout_s:
            title = self.page.title()
            if "cloudflare" not in title.lower() and "checking" not in title.lower():
                return True
            challenge = self.page.query_selector(
                "#challenge-running, #challenge-form, .cf-browser-verification"
            )
            if not challenge:
                return True
            time.sleep(1)
        return False

    def wait_for_job_list(self, *, timeout_ms: int = 15000) -> bool:
        """Chờ danh sách job render. Trả False nếu không thấy (trang rỗng/đổi layout)."""
        assert self.page is not None, "TopCvBrowser chưa start()"
        try:
            self.page.wait_for_selector(JOB_LIST_SELECTOR, timeout=timeout_ms)
            return True
        except Exception:  # noqa: BLE001 — timeout của Playwright
            return False

    def html(self) -> str:
        assert self.page is not None, "TopCvBrowser chưa start()"
        return self.page.content()


__all__ = [
    "BASE_URL",
    "DEFAULT_PARAMS",
    "JOB_LIST_SELECTOR",
    "SEARCH_URL",
    "TopCvBrowser",
    "build_search_url",
]
