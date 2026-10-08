from dataclasses import dataclass
from hashlib import sha256
import hmac
from pathlib import Path
import time
from typing import Annotated, Protocol
from urllib.parse import quote, urlencode

from fastapi import Depends

from app.config import settings


@dataclass(frozen=True)
class StoredObject:
    byte_size: int
    content_type: str | None


class ObjectStorage(Protocol):
    def upload_url(self, storage_key: str, content_type: str, byte_size: int) -> str: ...
    def download_url(self, storage_key: str, filename: str) -> str: ...
    def stat(self, storage_key: str) -> StoredObject | None: ...
    def read(self, storage_key: str) -> bytes: ...
    def delete(self, storage_key: str) -> None: ...


class S3ObjectStorage:
    def __init__(self) -> None:
        import boto3
        from botocore.config import Config

        options = {
            "aws_access_key_id": settings.object_storage_access_key,
            "aws_secret_access_key": settings.object_storage_secret_key,
            "region_name": settings.object_storage_region,
            "config": Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        }
        self.bucket = settings.object_storage_bucket
        self.internal = boto3.client(
            "s3", endpoint_url=settings.object_storage_endpoint, **options
        )
        self.public = boto3.client(
            "s3", endpoint_url=settings.object_storage_public_endpoint, **options
        )

    def upload_url(self, storage_key: str, content_type: str, byte_size: int) -> str:
        return self.public.generate_presigned_url(
            "put_object",
            Params={"Bucket": self.bucket, "Key": storage_key, "ContentType": content_type},
            ExpiresIn=settings.attachment_url_ttl_seconds,
        )

    def download_url(self, storage_key: str, filename: str) -> str:
        safe_filename = filename.replace('"', "")
        return self.public.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self.bucket,
                "Key": storage_key,
                "ResponseContentDisposition": f'attachment; filename="{safe_filename}"',
            },
            ExpiresIn=settings.attachment_url_ttl_seconds,
        )

    def stat(self, storage_key: str) -> StoredObject | None:
        from botocore.exceptions import ClientError

        try:
            result = self.internal.head_object(Bucket=self.bucket, Key=storage_key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise
        return StoredObject(
            byte_size=int(result["ContentLength"]), content_type=result.get("ContentType")
        )

    def read(self, storage_key: str) -> bytes:
        return self.internal.get_object(Bucket=self.bucket, Key=storage_key)["Body"].read()

    def delete(self, storage_key: str) -> None:
        self.internal.delete_object(Bucket=self.bucket, Key=storage_key)


class LocalObjectStorage:
    """Signed local storage for development; production can switch to S3."""

    def __init__(self) -> None:
        self.root = Path(settings.object_storage_local_path).resolve()

    def upload_url(self, storage_key: str, content_type: str, byte_size: int) -> str:
        expires = int(time.time()) + settings.attachment_url_ttl_seconds
        signature = self._sign("PUT", storage_key, expires, content_type, byte_size, "")
        query = urlencode({
            "expires": expires, "content_type": content_type,
            "byte_size": byte_size, "signature": signature,
        })
        return f"{settings.object_storage_local_public_url}/storage/uploads/{quote(storage_key)}?{query}"

    def download_url(self, storage_key: str, filename: str) -> str:
        expires = int(time.time()) + settings.attachment_url_ttl_seconds
        signature = self._sign("GET", storage_key, expires, "", 0, filename)
        query = urlencode({"expires": expires, "filename": filename, "signature": signature})
        return f"{settings.object_storage_local_public_url}/storage/downloads/{quote(storage_key)}?{query}"

    def stat(self, storage_key: str) -> StoredObject | None:
        path = self.path(storage_key)
        if not path.is_file():
            return None
        return StoredObject(byte_size=path.stat().st_size, content_type=None)

    def read(self, storage_key: str) -> bytes:
        return self.path(storage_key).read_bytes()

    def delete(self, storage_key: str) -> None:
        path = self.path(storage_key)
        if path.exists():
            path.unlink()

    def put(self, storage_key: str, content: bytes) -> None:
        path = self.path(storage_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".uploading")
        temporary.write_bytes(content)
        temporary.replace(path)

    def path(self, storage_key: str) -> Path:
        path = (self.root / storage_key).resolve()
        if self.root not in path.parents:
            raise ValueError("Invalid storage key")
        return path

    def verify_upload(
        self, storage_key: str, expires: int, content_type: str, byte_size: int, signature: str,
    ) -> bool:
        return self._verify("PUT", storage_key, expires, content_type, byte_size, "", signature)

    def verify_download(
        self, storage_key: str, expires: int, filename: str, signature: str,
    ) -> bool:
        return self._verify("GET", storage_key, expires, "", 0, filename, signature)

    def _verify(self, method, key, expires, content_type, byte_size, filename, signature) -> bool:
        if expires < int(time.time()):
            return False
        expected = self._sign(method, key, expires, content_type, byte_size, filename)
        return hmac.compare_digest(expected, signature)

    @staticmethod
    def _sign(method, key, expires, content_type, byte_size, filename) -> str:
        payload = f"{method}\n{key}\n{expires}\n{content_type}\n{byte_size}\n{filename}".encode()
        return hmac.new(
            settings.object_storage_signing_secret.encode(), payload, sha256
        ).hexdigest()


def get_object_storage() -> ObjectStorage:
    if settings.object_storage_driver == "s3":
        return S3ObjectStorage()
    return LocalObjectStorage()


ObjectStorageDep = Annotated[ObjectStorage, Depends(get_object_storage)]
