from __future__ import annotations

from pathlib import Path

import boto3
from botocore.config import Config

from paper_broker.logging import get_logger

log = get_logger("minio")


class MinioSync:
    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        *,
        secure: bool,
    ) -> None:
        self.bucket = bucket
        self._s3 = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(s3={"addressing_style": "path"}),
            use_ssl=secure,
        )

    def sync_tree(self, lake: Path) -> int:
        n = 0
        for path in lake.rglob("*"):
            if not path.is_file() or path.suffix == ".duckdb" or path.name.endswith(".wal"):
                continue
            key = path.relative_to(lake).as_posix()
            self._s3.upload_file(str(path), self.bucket, key)
            n += 1
        log.info("minio_synced", files=n, bucket=self.bucket)
        return n
