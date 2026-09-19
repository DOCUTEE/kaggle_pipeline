"""Preflight check cho Kaggle push — chạy TRƯỚC khi bật push thật.

Kiểm tra theo thứ tự:
    1. kaggle CLI có cài không (cần kaggle>=2.0 cho token mới)
    2. credentials: env KAGGLE_API_TOKEN (token KGAT_..., khuyên dùng)
       hoặc ~/.kaggle/kaggle.json {"username": ..., "key": ...}
    3. auth STRICT qua endpoint bắt buộc login (`competitions list`)
       — endpoint `datasets list` cho anonymous qua nên KHÔNG dùng để check auth
    4. từng dataset: đã tồn tại (→ push = version update) hay sẽ create mới;
       owner PHẢI khớp KAGGLE_USERNAME (push sang dataset user khác luôn 403)

Không tạo/sửa dataset nào, an toàn để chạy thoải mái.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class KaggleCheck:
    ok: bool = False
    cli_found: bool = False
    creds_found: bool = False
    creds_source: str = ""          # "KAGGLE_API_TOKEN" | "kaggle.json" | ""
    authed_user: str = ""
    datasets: dict = field(default_factory=dict)  # id -> {"ok": bool, "note": str}
    errors: list[str] = field(default_factory=list)


def _kaggle_bin() -> str | None:
    """Tìm binary kaggle: PATH trước, rồi tới cùng thư mục với python hiện tại
    (trường hợp gọi .venv/bin/python trực tiếp mà chưa activate venv)."""
    found = shutil.which("kaggle")
    if found:
        return found
    sibling = Path(sys.executable).parent / "kaggle"
    if sibling.exists():
        return str(sibling)
    return None


def _run(cmd: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def check_kaggle(dataset_ids: list[str]) -> KaggleCheck:
    """Chạy toàn bộ preflight cho 1 danh sách dataset id. Không push gì cả."""
    rep = KaggleCheck()

    # 1. CLI ─────────────────────────────────────────────────────────────
    kaggle_bin = _kaggle_bin()
    if not kaggle_bin:
        rep.errors.append("kaggle CLI not found. Cài: pip install 'kaggle>=2.0'")
        return rep
    rep.cli_found = True

    # 2. Credentials ─────────────────────────────────────────────────────
    api_token = os.getenv("KAGGLE_API_TOKEN", "")
    kaggle_json = Path.home() / ".kaggle" / "kaggle.json"
    file_user = ""
    if api_token:
        rep.creds_found = True
        rep.creds_source = "KAGGLE_API_TOKEN"
    elif kaggle_json.exists():
        rep.creds_found = True
        rep.creds_source = "kaggle.json"
        try:
            file_user = json.loads(kaggle_json.read_text()).get("username", "")
        except (OSError, ValueError):
            pass
    else:
        rep.errors.append(
            "Chưa có credentials. Lấy token ở kaggle.com/settings/api rồi làm 1 trong 2:\n"
            "  - export KAGGLE_API_TOKEN=<token KGAT_...> (khuyên dùng), hoặc\n"
            "  - đặt file ~/.kaggle/kaggle.json {\"username\": ..., \"key\": ...} + chmod 600"
        )
        return rep

    claimed_user = os.getenv("KAGGLE_USERNAME", "") or file_user

    # 3. Auth STRICT (competitions list bắt buộc login thật) ─────────────
    try:
        r = _run([kaggle_bin, "competitions", "list", "--csv"])
    except subprocess.TimeoutExpired:
        rep.errors.append("Kaggle API timeout — kiểm tra mạng.")
        return rep
    out = (r.stderr or r.stdout or "")
    if r.returncode != 0 or "Authentication required" in out:
        if "PermissionError" in out and ".kaggle" in out:
            rep.errors.append(
                "Kaggle CLI không tạo được ~/.kaggle (no write permission). "
                "Tạo tay: mkdir -p ~/.kaggle && chmod 700 ~/.kaggle."
            )
        else:
            rep.errors.append(
                "Auth thất bại (token không được chấp nhận). Lấy token mới ở "
                "kaggle.com/settings/api rồi export KAGGLE_API_TOKEN lại. "
                f"CLI báo: {out.strip()[:300]}"
            )
        return rep

    # 4. Dataset thuộc ai, tồn tại chưa ──────────────────────────────────
    owned: set[str] = set()
    try:
        r2 = _run([kaggle_bin, "datasets", "list", "--mine", "--csv"])
        if r2.returncode == 0:
            for line in (r2.stdout or "").splitlines()[1:]:  # bỏ header
                slug = line.split(",")[0].strip()
                if slug:
                    owned.add(slug)
    except subprocess.TimeoutExpired:
        pass

    rep.authed_user = claimed_user or "(theo token)"
    all_ok = True
    for ds in dataset_ids:
        owner = ds.split("/")[0] if "/" in ds else ""
        if ds in owned:
            rep.datasets[ds] = {"ok": True, "note": "đã tồn tại → push = version update."}
        elif claimed_user and owner and owner != claimed_user:
            rep.datasets[ds] = {
                "ok": False,
                "note": f"owner là '{owner}' nhưng KAGGLE_USERNAME='{claimed_user}' "
                        f"→ push sẽ 403. Set KAGGLE_USERNAME={owner} hoặc đổi id về "
                        f"'{claimed_user}/<slug>' (env {_env_for(ds)}).",
            }
            all_ok = False
        else:
            rep.datasets[ds] = {"ok": True, "note": "chưa tồn tại → lần push đầu sẽ create mới."}

    rep.ok = all_ok
    if not all_ok:
        rep.errors.append("Có dataset sai owner (xem chi tiết từng dataset ở trên).")
    return rep


def _env_for(dataset_id: str) -> str:
    slug = dataset_id.split("/")[-1]
    if "itviec" in slug:
        return "ITVIEC_KAGGLE_DATASET"
    if "arxiv" in slug:
        return "ARXIV_KAGGLE_DATASET"
    return "TOPCV_KAGGLE_DATASET"


def print_report(rep: KaggleCheck) -> None:
    print("\n=== Kaggle preflight ===")
    print(f"  CLI:         {'OK' if rep.cli_found else 'MISSING'}")
    print(f"  Credentials: {'OK (' + rep.creds_source + ')' if rep.creds_found else 'MISSING'}")
    print(f"  Authed user: {rep.authed_user or '-'}")
    for ds, info in rep.datasets.items():
        mark = "OK " if info["ok"] else "FAIL"
        print(f"  [{mark}] {ds}: {info['note']}")
    if rep.errors:
        print("\n  Lỗi:")
        for e in rep.errors:
            print(f"   - {e}")
    print(f"\n  Kết luận: {'SẴN SÀNG PUSH' if rep.ok else 'CHƯA PUSH ĐƯỢC — sửa các lỗi trên'}")
