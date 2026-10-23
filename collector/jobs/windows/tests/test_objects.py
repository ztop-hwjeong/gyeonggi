from io import BytesIO
from unittest.mock import Mock

import pytest
from botocore.exceptions import EndpointConnectionError
from collector_storage.config import ObjectStorageSettings
from collector_storage.objects import ObjectCredentials, RawObjectStore
from pydantic import AnyHttpUrl, SecretStr


@pytest.fixture
def objects(monkeypatch: pytest.MonkeyPatch) -> RawObjectStore:
    client = Mock()
    monkeypatch.setattr("collector_storage.objects.boto3.client", Mock(return_value=client))
    return RawObjectStore(
        ObjectStorageSettings(
            endpoint_url=AnyHttpUrl("http://127.0.0.1:9000"),
            bucket="collector-raw",
            region="us-east-1",
            credentials_block="test",
        ),
        ObjectCredentials(access_key=SecretStr("test"), secret_key=SecretStr("test")),
    )


def test_raw_bytes_round_trip_and_stream_closure(objects: RawObjectStore) -> None:
    body = b"<html>\r\n\xff\x00</html>"
    reference = objects.put("articles/test", body, "text/html; charset=euc-kr")
    stream = BytesIO(body)
    objects._client.get_object.return_value = {"Body": stream}
    assert objects.read(reference) == body
    assert stream.closed


@pytest.mark.parametrize("corrupted", [b"abd", b"ab", b"abcd"])
def test_corrupt_or_incomplete_object_fails(objects: RawObjectStore, corrupted: bytes) -> None:
    reference = objects.put("articles/test", b"abc", "text/html")
    stream = BytesIO(corrupted)
    objects._client.get_object.return_value = {"Body": stream}
    with pytest.raises(RuntimeError, match="무결성"):
        objects.read(reference)
    assert stream.closed


def test_upload_failure_is_visible(objects: RawObjectStore) -> None:
    objects._client.put_object.side_effect = EndpointConnectionError(endpoint_url="test")
    with pytest.raises(EndpointConnectionError):
        objects.put("articles/test", b"abc", "text/html")
