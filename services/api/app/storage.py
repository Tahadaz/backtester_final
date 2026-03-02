from __future__ import annotations

from threading import Lock

from botocore.client import Config
import boto3

from .config import settings


def _build_s3_client(endpoint_url: str):
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=settings.S3_ACCESS_KEY_ID,
        aws_secret_access_key=settings.S3_SECRET_ACCESS_KEY,
        region_name=settings.S3_REGION,
        config=Config(signature_version="s3v4"),
        use_ssl=settings.S3_USE_SSL,
        verify=False if not settings.S3_USE_SSL else True,
    )


def s3_client():
    return _build_s3_client(settings.S3_ENDPOINT_URL)


_bucket_lock = Lock()
_bucket_ready = False


def ensure_bucket() -> str:
    global _bucket_ready
    if _bucket_ready:
        return settings.S3_BUCKET

    with _bucket_lock:
        if _bucket_ready:
            return settings.S3_BUCKET

        s3 = s3_client()
        bucket = settings.S3_BUCKET
        try:
            s3.head_bucket(Bucket=bucket)
        except Exception:
            s3.create_bucket(Bucket=bucket)
        _bucket_ready = True
        return bucket


def put_bytes(object_key: str, data: bytes, content_type: str) -> None:
    ensure_bucket()
    s3 = s3_client()
    s3.put_object(Bucket=settings.S3_BUCKET, Key=object_key, Body=data, ContentType=content_type)


def delete_object(object_key: str) -> None:
    ensure_bucket()
    s3 = s3_client()
    s3.delete_object(Bucket=settings.S3_BUCKET, Key=object_key)


def presign_get(object_key: str, expires_seconds: int = 300) -> str:
    s3 = _build_s3_client(settings.S3_PRESIGN_ENDPOINT_URL)
    return s3.generate_presigned_url(
        ClientMethod="get_object",
        Params={"Bucket": settings.S3_BUCKET, "Key": object_key},
        ExpiresIn=expires_seconds,
    )
