"""
RailOS Shared MinIO / S3 Client Factory
==========================================
Centralises MinIO client creation used by the Cybersecurity Anomaly Scorer
and Acknowledgement Service.
"""
from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger(__name__)

MINIO_ENDPOINT = os.environ.get(
    "MINIO_ENDPOINT", "http://minio.railos.svc.cluster.local:9000"
)
MINIO_ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY", "railos-admin")
MINIO_SECRET_KEY = os.environ.get("MINIO_SECRET_KEY", "change-me")
FORENSIC_BUCKET = os.environ.get("FORENSIC_BUCKET", "railos-forensic-evidence")


def make_minio_client(
    endpoint_url: str | None = None,
    access_key: str | None = None,
    secret_key: str | None = None,
) -> Any:
    """Create a boto3 S3 client configured for MinIO.

    All parameters fall back to environment variables / defaults.
    """
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=endpoint_url or MINIO_ENDPOINT,
        aws_access_key_id=access_key or MINIO_ACCESS_KEY,
        aws_secret_access_key=secret_key or MINIO_SECRET_KEY,
        config=Config(signature_version="s3v4"),
    )
