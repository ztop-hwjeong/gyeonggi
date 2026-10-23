import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError
from prefect.exceptions import ObjectNotFound
from pydantic import AnyHttpUrl

import register_storage


@pytest.fixture
def setup_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple:
    access = tmp_path / "access"
    secret = tmp_path / "secret"
    access.write_text("TESTACCESS", encoding="utf-8")
    secret.write_text("test-secret", encoding="utf-8")
    settings = register_storage.StorageInitializationSettings(
        endpoint_url=AnyHttpUrl("http://localhost:9000"),
        bucket="test-bucket",
        region="us-east-1",
        credentials_block="test-block",
        access_key_file=access,
        secret_key_file=secret,
    )
    client = Mock()
    block = Mock()
    block.get.return_value = {"access_key": "TESTACCESS", "secret_key": "test-secret"}
    secret_class = Mock()
    secret_class.load.return_value = block
    monkeypatch.setattr(register_storage.boto3, "client", Mock(return_value=client))
    monkeypatch.setattr(register_storage, "Secret", secret_class)
    return settings, client, secret_class


def test_existing_bucket_and_credentials_are_preserved(setup_storage: tuple) -> None:
    settings, client, secret_class = setup_storage
    register_storage.initialize(settings)
    client.create_bucket.assert_not_called()
    secret_class.assert_not_called()
    client.close.assert_called_once()


def test_missing_bucket_and_secret_are_created(setup_storage: tuple) -> None:
    settings, client, secret_class = setup_storage
    client.head_bucket.side_effect = ClientError(
        {"ResponseMetadata": {"HTTPStatusCode": 404}, "Error": {"Code": "NoSuchBucket"}},
        "HeadBucket",
    )
    error = ValueError("missing block")
    error.__cause__ = ObjectNotFound(http_exc=Mock())
    secret_class.load.side_effect = error
    register_storage.initialize(settings)
    client.create_bucket.assert_called_once_with(Bucket=settings.bucket)
    value = secret_class.call_args.kwargs["value"].get_secret_value()
    assert json.loads(value) == {"access_key": "TESTACCESS", "secret_key": "test-secret"}
    secret_class.return_value.save.assert_called_once_with(settings.credentials_block)


def test_bucket_access_denied_does_not_create_bucket_or_secret(setup_storage: tuple) -> None:
    settings, client, secret_class = setup_storage
    client.head_bucket.side_effect = ClientError(
        {"ResponseMetadata": {"HTTPStatusCode": 403}, "Error": {"Code": "AccessDenied"}},
        "HeadBucket",
    )
    with pytest.raises(ClientError):
        register_storage.initialize(settings)
    client.create_bucket.assert_not_called()
    secret_class.assert_not_called()
    client.close.assert_called_once()


def test_existing_secret_mismatch_fails_without_overwrite(setup_storage: tuple) -> None:
    settings, _, secret_class = setup_storage
    secret_class.load.return_value.get.return_value = {"access_key": "OTHER"}
    with pytest.raises(RuntimeError, match="불일치"):
        register_storage.initialize(settings)
    secret_class.assert_not_called()


def test_unrelated_block_error_is_not_treated_as_missing(setup_storage: tuple) -> None:
    settings, _, secret_class = setup_storage
    secret_class.load.side_effect = ValueError("invalid credentials")
    with pytest.raises(ValueError, match="invalid credentials"):
        register_storage.initialize(settings)
    secret_class.assert_not_called()
