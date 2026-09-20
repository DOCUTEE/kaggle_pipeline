"""Browser client cho TopCV — vòng đời browser + truy cập trang (I/O thuần).

Tách khỏi parser để:
- phần parse HTML test được offline (không cần browser),
- phần điều khiển browser chỉ còn 1 chỗ (dễ thay khi Cloudflare đổi).

**Vì sao dùng CloakBrowser** (không dùng Playwright thường): Cloudflare của topcv
trả trang "Attention Required!" ngay từ `?page=2` với Chromium thường — đo trực tiếp,
không phụ thuộc delay, click link phân trang cũng bị. CloakBrowser là Chromium được
patch fingerprint ở tầng C++ nên phân trang chạy bình thường (đo: 55 page → 2.698 job).

CloakBrowser dùng chính API Playwright (`page.goto/title/content/...`) nên
parser/scraper không cần biết. Import **lazy** trong `start()` để module này
import được khi chưa cài browser.
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
    """Bọc CloakBrowser: mở trang, chờ Cloudflare, trả HTML."""

    def __init__(self, headless: bool = True) -> None:
        self.headless = headless
        self.browser: Optional["Browser"] = None
        self.page: Optional["Page"] = None

    # cho phép `with TopCvBrowser() as browser:` — tự đóng kể cả khi lỗi
    def __enter__(self) -> "TopCvBrowser":
        self.start()
        return self

    def __exit__(self, *exc_info) -> None:
        self.stop()

    def start(self) -> None:
        """Khởi động CloakBrowser (fingerprint đã patch trong binary)."""
        from cloakbrowser import launch  # lazy: không cần cài browser khi chỉ import module

        self.browser = launch(headless=self.headless)
        self.page = self.browser.new_page()

    def stop(self) -> None:
        """Đóng browser (gọi được nhiều lần)."""
        if self.browser:
            try:
                self.browser.close()
            except Exception:  # noqa: BLE001 — đóng browser lỗi không nên làm chết run
                pass
            self.browser = None
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
