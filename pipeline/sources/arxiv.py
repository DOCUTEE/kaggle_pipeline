"""arXiv source adapter — thu paper + PDF theo đúng BaseSource pattern.

Nguồn: arXiv Export API (http://export.arxiv.org/api/query), không cần auth.
Tuân thủ policy arXiv: delay 3s giữa các request, User-Agent rõ ràng.

Cấu hình qua env (để runner 6 bước không phải đổi signature):
    ARXIV_QUERY        — vd "cat:cs.AI" | "all:large language model" (default: cat:cs.AI)
    ARXIV_MAX_RESULTS  — tổng số paper tối đa cho chạy 1 lần (default: 100)
    ARXIV_SORT_BY      — submitted | relevance | lastUpdatedDate (default: submitted)
    ARXIV_SORT_ORDER   — descending | ascending (default: descending)
    ARXIV_DOWNLOAD_PDF — "1" tải PDF, "0" chỉ lấy metadata (default: "1")
    ARXIV_PAGE_SIZE    — số paper mỗi request API (default: 100, max của arXiv)

Map `max_pages` của runner:
    - Nếu CLI truyền --max-pages N -> max_results = N * ARXIV_PAGE_SIZE (test nhanh)
    - Nếu None -> dùng ARXIV_MAX_RESULTS

Output (idempotent, atomic write):
    data_dir/arxiv_YYYYMMDD_HHMMSS.json + .csv
    data_dir/arxiv_latest.json + .csv  (ghi đè mỗi lần chạy)
    data_dir/pdfs/<safe_id>.pdf        (skip nếu đã tồn tại)
    metadata mỗi paper có thêm: pdf_local, minio_key, pdf_location
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import time
from datetime import datetime
from pathlib import Path

from pipeline.sources.base import ScrapeResult

logger = logging.getLogger(__name__)

API_URL = "http://export.arxiv.org/api/query"
USER_AGENT = "kaggle-pipeline-arxiv/1.0 (mailto:pipeline@localhost)"
REQUEST_DELAY_S = 3.0


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _clean_ws(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _safe_id(arxiv_id: str) -> str:
    # "2609.19146v1" -> "2609.19146v1", "hep-th/9901001v1" -> "hep-th_9901001v1"
    return re.sub(r"[^A-Za-z0-9.\-_]", "_", arxiv_id)


def _fetch_batch(query: str, start: int, page_size: int,
                 sort_by: str, sort_order: str, timeout: int):
    """Gọi 1 request arXiv API, trả list dict entries (đã parse)."""
    import requests

    # Chuẩn hóa sortBy theo arXiv API: relevance | lastUpdatedDate | submittedDate
    sort_map = {"submitted": "submittedDate", "updated": "lastUpdatedDate",
                "lastupdated": "lastUpdatedDate", "relevance": "relevance"}
    sort_by = sort_map.get(sort_by.strip(), sort_by.strip() or "submittedDate")
    if sort_by not in ("relevance", "lastUpdatedDate", "submittedDate"):
        sort_by = "submittedDate"
    if sort_order not in ("ascending", "descending"):
        sort_order = "descending"

    params = {
        "search_query": query,
        "start": start,
        "max_results": page_size,
        "sortBy": sort_by,
        "sortOrder": sort_order,
    }
    resp = requests.get(API_URL, params=params, timeout=timeout,
                        headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    return _parse_atom(resp.text)


def _parse_atom(xml_text: str) -> list[dict]:
    """Parse Atom XML. Ưu tiên feedparser, fallback xml.etree."""
    try:
        import feedparser
        feed = feedparser.parse(xml_text)
        out = []
        for e in feed.entries:
            raw_id = e.get("id", "")
            # id dạng http://arxiv.org/abs/2609.19146v1
            m = re.search(r"/abs/([^/]+)$", raw_id)
            arxiv_id = m.group(1) if m else raw_id
            authors = [a.get("name", "") for a in e.get("authors", []) if a.get("name")]
            tags = [t.get("term", "") for t in e.get("tags", []) if t.get("term")]
            # pdf link
            pdf_url = ""
            for link in e.get("links", []):
                if link.get("type") == "application/pdf" or "pdf" in link.get("href", ""):
                    pdf_url = link["href"]
                    break
            if not pdf_url and arxiv_id:
                pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
            out.append({
                "arxiv_id": arxiv_id,
                "title": _clean_ws(e.get("title", "")),
                "authors": authors,
                "abstract": _clean_ws(e.get("summary", "")),
                "categories": tags,
                "primary_category": tags[0] if tags else "",
                "published": e.get("published", ""),
                "updated": e.get("updated", ""),
                "pdf_url": pdf_url,
                "comment": _clean_ws(e.get("arxiv_comment", "")),
                "journal_ref": _clean_ws(e.get("arxiv_journal_ref", "")),
                "doi": e.get("arxiv_doi", "") or "",
            })
        return out
    except ImportError:
        pass

    # Fallback: xml.etree (không cần feedparser)
    import xml.etree.ElementTree as ET
    ns = {"a": "http://www.w3.org/2005/Atom",
          "arxiv": "http://arxiv.org/schemas/atom"}
    root = ET.fromstring(xml_text)
    out = []
    for entry in root.findall("a:entry", ns):
        def _t(tag):
            el = entry.find(tag, ns)
            return _clean_ws(el.text) if el is not None and el.text else ""
        raw_id = _t("a:id")
        m = re.search(r"/abs/([^/]+)$", raw_id)
        arxiv_id = m.group(1) if m else raw_id
        authors = [(_clean_ws(a.find("a:name", ns).text)
                    if a.find("a:name", ns) is not None else "")
                   for a in entry.findall("a:author", ns)]
        authors = [a for a in authors if a]
        cats = [c.get("term", "") for c in entry.findall("a:category", ns)]
        pdf_url = ""
        for link in entry.findall("a:link", ns):
            if link.get("type") == "application/pdf":
                pdf_url = link.get("href", "")
        if not pdf_url and arxiv_id:
            pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
        out.append({
            "arxiv_id": arxiv_id,
            "title": _t("a:title"),
            "authors": authors,
            "abstract": _t("a:summary"),
            "categories": cats,
            "primary_category": cats[0] if cats else "",
            "published": _t("a:published"),
            "updated": _t("a:updated"),
            "pdf_url": pdf_url,
            "comment": _t("arxiv:comment"),
            "journal_ref": _t("arxiv:journal_ref"),
            "doi": _t("arxiv:doi"),
        })
    return out


def _download_pdf(pdf_url: str, dest: Path, timeout: int) -> bool:
    """Tải PDF về dest. Trả True nếu có file (mới tải hoặc đã tồn tại)."""
    if dest.exists() and dest.stat().st_size > 0:
        return True
    import requests
    try:
        with requests.get(pdf_url, timeout=timeout, stream=True,
                          headers={"User-Agent": USER_AGENT}) as r:
            r.raise_for_status()
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
        return dest.exists() and dest.stat().st_size > 0
    except Exception as exc:
        logger.warning("PDF download failed %s: %s", pdf_url, exc)
        return False


def _atomic_write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class ArxivSource:
    name = "arxiv"

    def scrape(
        self,
        data_dir: Path,
        *,
        max_pages: int | None = None,
        workers: int = 1,
        timeout: int = 30,
        verbose: bool = False,
    ) -> ScrapeResult:
        _ = (workers, verbose)  # arXiv yêu cầu request tuần tự (3s delay), giữ param cho đồng nhất
        data_dir = Path(data_dir)
        data_dir.mkdir(parents=True, exist_ok=True)

        query = os.getenv("ARXIV_QUERY", "cat:cs.AI").strip() or "cat:cs.AI"
        sort_by = os.getenv("ARXIV_SORT_BY", "submittedDate")
        sort_order = os.getenv("ARXIV_SORT_ORDER", "descending")
        page_size = max(1, min(_env_int("ARXIV_PAGE_SIZE", 100), 500))
        download_pdf = os.getenv("ARXIV_DOWNLOAD_PDF", "1") == "1"

        if max_pages is not None:
            max_results = max_pages * page_size
        else:
            max_results = _env_int("ARXIV_MAX_RESULTS", 100)
        max_results = max(1, max_results)

        logger.info("[arxiv] query=%r max_results=%d sort=%s/%s pdf=%s",
                    query, max_results, sort_by, sort_order, download_pdf)

        # 1. Fetch metadata theo batch (arXiv tối đa ~ vài trăm/request)
        papers: list[dict] = []
        start = 0
        while len(papers) < max_results:
            batch_n = min(page_size, max_results - len(papers))
            if start > 0:
                time.sleep(REQUEST_DELAY_S)  # politeness delay
            batch = _fetch_batch(query, start, batch_n, sort_by, sort_order, timeout)
            if not batch:
                break
            papers.extend(batch)
            logger.info("[arxiv] fetched %d/%d (start=%d)", len(papers), max_results, start)
            start += len(batch)
            if len(batch) < batch_n:
                break  # hết kết quả

        # 2. Tải PDF + upload MinIO (idempotent: skip file đã có)
        from pipeline import minio_store

        pdf_dir = data_dir / "pdfs"
        pdf_dir.mkdir(parents=True, exist_ok=True)
        n_pdf, n_minio = 0, 0
        scrape_date = datetime.now().strftime("%Y-%m-%d")
        for p in papers:
            aid = p.get("arxiv_id", "")
            safe = _safe_id(aid) or "unknown"
            local_pdf = pdf_dir / f"{safe}.pdf"
            if download_pdf and aid:
                time.sleep(1.0)  # nhẹ nhàng với export.arxiv.org / arxiv.org
                if _download_pdf(p.get("pdf_url", ""), local_pdf, timeout):
                    n_pdf += 1
                    ok, loc = minio_store.upload_file(local_pdf, f"arxiv/{safe}.pdf")
                    p["pdf_local"] = str(local_pdf.resolve())
                    p["minio_key"] = f"arxiv/{safe}.pdf" if ok else ""
                    p["pdf_location"] = loc
                    if ok:
                        n_minio += 1
                else:
                    p["pdf_local"] = ""
                    p["minio_key"] = ""
                    p["pdf_location"] = ""
            else:
                p["pdf_local"] = ""
                p["minio_key"] = ""
                p["pdf_location"] = ""
            p["scrape_date"] = scrape_date
            p["query"] = query

        # 3. Lưu metadata (atomic, latest overwrite = idempotent ở mức file)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        stamp_json = data_dir / f"arxiv_{ts}.json"
        stamp_csv = data_dir / f"arxiv_{ts}.csv"
        latest_json = data_dir / "arxiv_latest.json"
        latest_csv = data_dir / "arxiv_latest.csv"

        payload = {"query": query, "scrape_date": scrape_date,
                   "count": len(papers), "papers": papers}
        _atomic_write_json(stamp_json, payload)
        _atomic_write_json(latest_json, payload)

        # CSV phẳng để load Postgres / Kaggle (authors/categories join bằng ";")
        try:
            import pandas as pd
            rows = [{
                "arxiv_id": p.get("arxiv_id", ""),
                "title": p.get("title", ""),
                "authors": "; ".join(p.get("authors", [])),
                "abstract": p.get("abstract", ""),
                "categories": ";".join(p.get("categories", [])),
                "primary_category": p.get("primary_category", ""),
                "published": p.get("published", ""),
                "updated": p.get("updated", ""),
                "pdf_url": p.get("pdf_url", ""),
                "pdf_local": p.get("pdf_local", ""),
                "minio_key": p.get("minio_key", ""),
                "pdf_location": p.get("pdf_location", ""),
                "comment": p.get("comment", ""),
                "journal_ref": p.get("journal_ref", ""),
                "doi": p.get("doi", ""),
                "scrape_date": p.get("scrape_date", ""),
                "query": p.get("query", ""),
            } for p in papers]
            df = pd.DataFrame(rows)
            df.to_csv(stamp_csv, index=False)
            df.to_csv(latest_csv, index=False)
        except Exception as exc:
            logger.warning("[arxiv] CSV write failed: %s", exc)
            stamp_csv, latest_csv = None, None

        logger.info("[arxiv] done: %d papers, %d PDFs, %d MinIO uploads",
                    len(papers), n_pdf, n_minio)
        return ScrapeResult(
            source=self.name,
            count=len(papers),
            raw_dir=data_dir,
            latest_csv=Path(latest_csv) if latest_csv and Path(latest_csv).exists() else None,
            latest_json=latest_json,
            extra={"pdfs_downloaded": n_pdf, "minio_uploaded": n_minio, "query": query},
        )
