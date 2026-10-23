from hashlib import sha256
from typing import Self

import boto3
from botocore.config import Config
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from config import ObjectStorageSettings


class ObjectCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    access_key: SecretStr
    secret_key: SecretStr


class RawObject(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    bucket: str
    key: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    byte_length: int = Field(ge=0)


class RawObjectStore:
    def __init__(self, settings: ObjectStorageSettings, credentials: ObjectCredentials) -> None:
        self._bucket = settings.bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=str(settings.endpoint_url),
            region_name=settings.region,
            aws_access_key_id=credentials.access_key.get_secret_value(),
            aws_secret_access_key=credentials.secret_key.get_secret_value(),
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                connect_timeout=settings.connect_timeout_seconds,
                read_timeout=settings.read_timeout_seconds,
                retries={"mode": "standard", "total_max_attempts": 3},
            ),
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self._client.close()

    def put(self, key: str, body: bytes, content_type: str) -> RawObject:
        result = RawObject(
            bucket=self._bucket, key=key, sha256=sha256(body).hexdigest(), byte_length=len(body)
        )
        self._client.put_object(
            Bucket=result.bucket,
            Key=result.key,
            Body=body,
            ContentType=content_type or "application/octet-stream",
            Metadata={"sha256": result.sha256},
            IfNoneMatch="*",
        )
        return result

    def read(self, reference: RawObject) -> bytes:
        response = self._client.get_object(Bucket=reference.bucket, Key=reference.key)
        stream = response["Body"]
        try:
            body = stream.read(reference.byte_length + 1)
        finally:
            stream.close()
        if len(body) != reference.byte_length or sha256(body).hexdigest() != reference.sha256:
            raise RuntimeError("수집 원본 객체 무결성 불일치")
        return body
