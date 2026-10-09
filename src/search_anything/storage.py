"""S3-compatible object storage, isolated behind one application interface."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import BinaryIO

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from search_anything.settings import Settings, get_settings


@dataclass(frozen=True)
class ObjectRead:
    body: BinaryIO
    content_length: int
    content_type: str
    content_range: str | None
    is_partial: bool


class S3ObjectStorage:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.client = boto3.client(
            "s3",
            endpoint_url=self.settings.storage_endpoint,
            region_name=self.settings.storage_region,
            aws_access_key_id=self.settings.storage_access_key,
            aws_secret_access_key=self.settings.storage_secret_key,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )
        self.bucket = self.settings.storage_bucket

    async def ensure_bucket(self) -> None:
        await asyncio.to_thread(self._ensure_bucket)

    async def check_bucket(self) -> None:
        await asyncio.to_thread(self.client.head_bucket, Bucket=self.bucket)

    def _ensure_bucket(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError as error:
            code = str(error.response.get("Error", {}).get("Code", ""))
            if code not in {"404", "NoSuchBucket", "NotFound"}:
                raise
            self.client.create_bucket(Bucket=self.bucket)

    async def put_file(
        self,
        key: str,
        fileobj: BinaryIO,
        content_type: str,
        content_hash: str,
    ) -> None:
        await asyncio.to_thread(
            self.client.upload_fileobj,
            fileobj,
            self.bucket,
            key,
            ExtraArgs={
                "ContentType": content_type,
                "Metadata": {"sha256": content_hash},
            },
        )

    async def get_object(self, key: str, byte_range: str | None = None) -> ObjectRead:
        return await asyncio.to_thread(self._get_object, key, byte_range)

    def _get_object(self, key: str, byte_range: str | None) -> ObjectRead:
        params: dict[str, str] = {"Bucket": self.bucket, "Key": key}
        if byte_range:
            params["Range"] = byte_range
        result = self.client.get_object(**params)
        return ObjectRead(
            body=result["Body"],
            content_length=int(result["ContentLength"]),
            content_type=result.get("ContentType", "application/octet-stream"),
            content_range=result.get("ContentRange"),
            is_partial="ContentRange" in result,
        )

    async def head_object(self, key: str) -> dict[str, object]:
        return await asyncio.to_thread(
            self.client.head_object, Bucket=self.bucket, Key=key
        )

    async def delete_object(self, key: str) -> None:
        await asyncio.to_thread(self.client.delete_object, Bucket=self.bucket, Key=key)

    async def presigned_get_url(self, key: str) -> str:
        return await asyncio.to_thread(
            self.client.generate_presigned_url,
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=self.settings.storage_presign_seconds,
        )
