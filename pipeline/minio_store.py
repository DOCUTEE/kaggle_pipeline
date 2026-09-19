"""MinIO object storage helper — lưu file PDF, fallback về local khi MinIO chưa chạy.

Env:
    MINIO_ENDPOINT   — vd "localhost:9000" (không scheme). Default: localhost:9000
    MINIO_ACCESS_KEY — default: minioadmin
    MINIO_SECRET_KEY — default: minioadmin
    MINIO_BUCKET     — default: arxiv-pdfs
    MINIO_SECURE     — "1" = https, default "0" = http (local/dev)
    MINIO_REGION     — default: us-east-1
    S3_ENDPOINT_URL  — nếu set thì ưu tiên dùng full URL này (tương thích AWS S3)

Hành vi:
    - Nếu boto3 chưa cài hoặc MinIO không reachable -> trả về fallback local,
      KHÔNG raise, để pipeline 1 lần vẫn thu được metadata + PDF local.
    - Nếu upload OK -> trả về s3://bucket/key.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def minio_config() -> dict:
    endpoint = os.getenv("MINIO_ENDPOINT", "localhost:9000").strip()
    # Cho phép truyền cả full URL
    if endpoint.startswith("http://"):
        endpoint = endpoint[len("http://"):]
    if endpoint.startswith("https://"):
        endpoint = endpoint[len("https://"):]
    secure = os.getenv("MINIO_SECURE", "0") == "1"
    endpoint_url = os.getenv("S3_ENDPOINT_URL") or f"{'https' if secure else 'http'}://{endpoint}"
    return {
        "endpoint_url": endpoint_url,
        "aws_access_key_id": os.getenv("MINIO_ACCESS_KEY", "minioadmin"),
        "aws_secret_access_key": os.getenv("MINIO_SECRET_KEY", "minioadmin"),
        "bucket": os.getenv("MINIO_BUCKET", "arxiv-pdfs"),
        "region": os.getenv("MINIO_REGION", "us-east-1"),
    }


def get_client():
    """Trả về boto3 S3 client hoặc None nếu không dùng được."""
    try:
        import boto3
    except ImportError:
        logger.warning("boto3 chưa cài (pip install boto3) — dùng fallback local")
        return None
    cfg = minio_config()
    try:
        client = boto3.client(
            "s3",
            endpoint_url=cfg["endpoint_url"],
            aws_access_key_id=cfg["aws_access_key_id"],
            aws_secret_access_key=cfg["aws_secret_access_key"],
            region_name=cfg["region"],
        )
        # list_buckets để kiểm tra kết nối (timeout nhanh)
        client.list_buckets()
        return client
    except Exception as exc:  # MinIO chưa chạy / sai key -> fallback
        logger.warning("MinIO không reachable (%s): %s — dùng fallback local",
                       cfg["endpoint_url"], exc)
        return None


def ensure_bucket(client, bucket: str) -> None:
    try:
        client.head_bucket(Bucket=bucket)
    except Exception:
        try:
            client.create_bucket(Bucket=bucket)
            logger.info("MinIO: created bucket %s", bucket)
        except Exception as exc:
            logger.warning("MinIO: cannot create bucket %s: %s", bucket, exc)


def upload_file(local_path: Path, object_key: str) -> tuple[bool, str]:
    """Upload 1 file lên MinIO. Trả (ok, location).

    - ok=True  -> location = "s3://bucket/key"
    - ok=False -> location = "file://<local_path>" (fallback, file vẫn nằm local)
    Không raise exception.
    """
    local_path = Path(local_path)
    cfg = minio_config()
    bucket = cfg["bucket"]
    client = get_client()
    if client is None:
        return False, f"file://{local_path.resolve()}"
    try:
        ensure_bucket(client, bucket)
        client.upload_file(str(local_path), bucket, object_key)
        return True, f"s3://{bucket}/{object_key}"
    except Exception as exc:
        logger.warning("MinIO upload failed %s: %s — giữ file local", object_key, exc)
        return False, f"file://{local_path.resolve()}"
