import socket
from unittest.mock import Mock

import pytest

from articles.requests import RequestStoppedError, validate_public_url


@pytest.mark.parametrize(
    "url", ["file:///etc/passwd", "http://user:pass@example.org", "ftp://example.org"]
)
def test_non_article_urls_are_rejected(url: str) -> None:
    with pytest.raises(RequestStoppedError):
        validate_public_url(url)


def test_private_redirect_destination_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        Mock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))]),
    )
    with pytest.raises(RequestStoppedError):
        validate_public_url("http://example.org/admin")
