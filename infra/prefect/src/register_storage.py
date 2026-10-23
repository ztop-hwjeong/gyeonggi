import json
from pathlib import Path
from typing import cast

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from prefect.blocks.system import Secret
from prefect.exceptions import ObjectNotFound
from pydantic import AnyHttpUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class StorageInitializationSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OBJECT_STORAGE_", extra="ignore")

    endpoint_url: AnyHttpUrl
    bucket: str = Field(min_length=3)
    region: str = Field(min_length=1)
    credentials_block: str = Field(min_length=1)
    access_key_file: Path
    secret_key_file: Path


def initialize(settings: StorageInitializationSettings) -> None:
    access_key = settings.access_key_file.read_text(encoding="utf-8").strip()
    secret_key = settings.secret_key_file.read_text(encoding="utf-8").strip()
    if not access_key or not secret_key:
        raise ValueError("객체 저장소 자격 증명 필요")
    client = boto3.client(
        "s3",
        endpoint_url=str(settings.endpoint_url),
        region_name=settings.region,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
    try:
        try:
            client.head_bucket(Bucket=settings.bucket)
        except ClientError as error:
            if error.response["ResponseMetadata"]["HTTPStatusCode"] != 404:
                raise
            client.create_bucket(Bucket=settings.bucket)
    finally:
        client.close()
    value = json.dumps({"access_key": access_key, "secret_key": secret_key})
    try:
        existing = cast(Secret, Secret.load(settings.credentials_block))
    except ValueError as error:
        if not isinstance(error.__cause__, ObjectNotFound):
            raise
        Secret(value=SecretStr(value)).save(settings.credentials_block)
    else:
        if existing.get() != json.loads(value):
            raise RuntimeError("기존 Prefect 객체 저장소 자격 증명과 불일치")
    print("객체 저장소 버킷 및 자격 증명 등록 확인")


if __name__ == "__main__":
    initialize(StorageInitializationSettings.model_validate({}))
