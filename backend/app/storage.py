"""Fichiers téléversés sur un stockage compatible S3 (activé par OUTILLAGE_S3_BUCKET ; sinon dossier local, voir utils)."""
import mimetypes
from functools import lru_cache
from typing import Iterator, Tuple

from . import config

PRESIGNED_SECONDS = 300


def enabled() -> bool:
    return bool(config.S3_BUCKET)


@lru_cache(maxsize=1)
def _client():
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=config.S3_ENDPOINT,
        region_name=config.S3_REGION,
        aws_access_key_id=config.S3_ACCESS_KEY,
        aws_secret_access_key=config.S3_SECRET_KEY,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def put(key: str, content: bytes):
    content_type = mimetypes.guess_type(key)[0] or "application/octet-stream"
    _client().put_object(Bucket=config.S3_BUCKET, Key=key, Body=content, ContentType=content_type)


def presigned_url(key: str) -> str:
    return _client().generate_presigned_url("get_object", Params={"Bucket": config.S3_BUCKET, "Key": key}, ExpiresIn=PRESIGNED_SECONDS)


def list_files() -> Iterator[Tuple[str, float]]:
    for page in _client().get_paginator("list_objects_v2").paginate(Bucket=config.S3_BUCKET):
        for item in page.get("Contents", []):
            yield item["Key"], item["LastModified"].timestamp()


def delete(key: str):
    _client().delete_object(Bucket=config.S3_BUCKET, Key=key)
