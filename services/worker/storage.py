import boto3
from botocore.client import Config
from threading import Lock
from services.worker.config import settings

def s3_client():
    return boto3.client(
        "s3",
        endpoint_url=settings.S3_ENDPOINT_URL,
        aws_access_key_id=settings.S3_ACCESS_KEY_ID,
        aws_secret_access_key=settings.S3_SECRET_ACCESS_KEY,
        region_name=settings.S3_REGION,
        config=Config(signature_version="s3v4"),
        use_ssl=settings.S3_USE_SSL,
        verify=False if not settings.S3_USE_SSL else True,
    )


_bucket_lock = Lock()
_bucket_ready = False


def ensure_bucket():
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
