from __future__ import annotations

import gzip
import json
import os
from dataclasses import dataclass
from typing import Any


@dataclass
class R2Store:
    bucket: str
    account_id: str
    access_key_id: str
    secret_access_key: str

    @classmethod
    def from_env(cls) -> R2Store:
        required = {
            "bucket": os.environ.get("R2_BUCKET"),
            "account_id": os.environ.get("R2_ACCOUNT_ID"),
            "access_key_id": os.environ.get("R2_ACCESS_KEY_ID"),
            "secret_access_key": os.environ.get("R2_SECRET_ACCESS_KEY"),
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise RuntimeError(f"Missing R2 environment values: {', '.join(missing)}")
        return cls(**required)  # type: ignore[arg-type]

    @property
    def client(self):
        try:
            import boto3
        except ImportError as exc:
            raise RuntimeError("boto3 is required for R2 access; install requirements.txt") from exc
        return boto3.client(
            service_name="s3",
            endpoint_url=f"https://{self.account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=self.access_key_id,
            aws_secret_access_key=self.secret_access_key,
            region_name="auto",
        )

    def put_json(self, key: str, value: Any, *, cache_control: str = "public, max-age=120") -> None:
        body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=body,
            ContentType="application/json; charset=utf-8",
            CacheControl=cache_control,
        )

    def put_gzip_json(self, key: str, value: Any) -> None:
        body = gzip.compress(json.dumps(value, ensure_ascii=False).encode("utf-8"), compresslevel=9)
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=body,
            ContentType="application/json; charset=utf-8",
            ContentEncoding="gzip",
            CacheControl="private, max-age=31536000, immutable",
        )

    def get_json(self, key: str) -> Any:
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        body = response["Body"].read()
        if response.get("ContentEncoding") == "gzip" or key.endswith(".gz"):
            body = gzip.decompress(body)
        return json.loads(body.decode("utf-8"))

    def get_json_optional(self, key: str) -> Any | None:
        try:
            return self.get_json(key)
        except Exception as exc:
            response = getattr(exc, "response", {})
            code = str(response.get("Error", {}).get("Code", ""))
            status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if code in {"NoSuchKey", "404"} or status == 404:
                return None
            raise

    def list_keys(self, prefix: str, *, limit: int = 1000) -> list[str]:
        paginator = self.client.get_paginator("list_objects_v2")
        pages = paginator.paginate(
            Bucket=self.bucket,
            Prefix=prefix,
            PaginationConfig={"PageSize": min(max(limit, 1), 1000)},
        )
        keys = [item["Key"] for page in pages for item in page.get("Contents", [])]
        return sorted(keys)[-limit:]


def public_cors_policy(origin: str = "https://yu-zora.com") -> list[dict[str, Any]]:
    """Return the minimal dashboard CORS policy for public summary reads."""
    return [
        {
            "AllowedOrigins": [origin],
            "AllowedMethods": ["GET", "HEAD"],
            "AllowedHeaders": ["If-None-Match"],
            "ExposeHeaders": ["ETag"],
            "MaxAgeSeconds": 3600,
        }
    ]

