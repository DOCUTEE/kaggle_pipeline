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
#: Lưu ý: CSS class selector khớp theo TỪNG token — `.job-item` KHÔNG khớp
#: `job-item-search-result` (markup thật của topcv), nên phải liệt kê cả hai.
JOB_LIST_SELECTOR = ".job-item-search-result, .job-list-search, .job-item, [data-job-id]"

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

    def wait_for_cloudflare(self, timeout_s: int = 30) -> bool:
        """Chờ challenge Cloudflare xong. Trả False nếu quá hạn.

        Trang chặn thật gặp phải: "Attention Required! | Cloudflare" (chặn hẳn)
        và "Just a moment..." (đang giải challenge).
        """
        assert self.page is not None, "TopCvBrowser chưa start()"
        blocked_markers = ("cloudflare", "checking", "attention required", "just a moment")
        start = time.time()
        while time.time() - start < timeout_s:
            title = self.page.title().lower()
            # Chỉ dựa vào title: trang chặn "Attention Required! | Cloudflare" KHÔNG có
            # #challenge-form, nên nếu thoát sớm theo element sẽ báo "đã qua" sai.
            if not any(marker in title for marker in blocked_markers):
                return True
            time.sleep(1)
        return False

    def wait_for_job_list(self, *, timeout_ms: int = 25000) -> bool:
        """Chờ card job có trong DOM. Trả False nếu quá hạn.

        Dùng `state="attached"`: mặc định của Playwright là "visible", mà topcv
        render card trong container chưa hiện → chờ visible sẽ timeout dù DOM đã có.
        """
        assert self.page is not None, "TopCvBrowser chưa start()"
        try:
            self.page.wait_for_selector(JOB_LIST_SELECTOR, state="attached", timeout=timeout_ms)
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
