import ipaddress
import socket
from hashlib import sha256
from urllib.parse import urlsplit

from prefect.client.orchestration import get_client
from prefect.client.schemas.actions import GlobalConcurrencyLimitCreate
from prefect.concurrency.sync import rate_limit
from prefect.exceptions import ObjectAlreadyExists, ObjectNotFound

from config import DetailSettings


class RequestStoppedError(RuntimeError):
    pass


def validate_public_url(url: str) -> str:
    parsed = urlsplit(url)
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise RequestStoppedError("공개 HTTP 원문 주소 필요")
    addresses = socket.getaddrinfo(
        parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)
    )
    if not addresses or any(
        not ipaddress.ip_address(address[4][0]).is_global for address in addresses
    ):
        raise RequestStoppedError("공개 인터넷 원문 주소 필요")
    return url


class PublisherRateLimiter:
    def __init__(self, settings: DetailSettings) -> None:
        self._settings = settings

    def acquire(self, url: str) -> None:
        host = urlsplit(url).hostname
        if host is None:
            raise RequestStoppedError("원문 호스트 필요")
        name = "publisher-http-" + sha256(host.lower().encode()).hexdigest()[:24]
        with get_client(sync_client=True) as client:
            try:
                limit = client.read_global_concurrency_limit_by_name(name)
            except ObjectNotFound:
                try:
                    client.create_global_concurrency_limit(
                        GlobalConcurrencyLimitCreate(
                            name=name,
                            limit=1,
                            slot_decay_per_second=1 / self._settings.publisher_interval_seconds,
                        )
                    )
                except ObjectAlreadyExists:
                    pass
                limit = client.read_global_concurrency_limit_by_name(name)
        if not limit.active or limit.limit != 1 or limit.slot_decay_per_second <= 0:
            raise RequestStoppedError("언론사 요청 속도 제한 비활성 또는 설정 오류")
        rate_limit(name, timeout_seconds=self._settings.rate_limit_timeout_seconds, strict=True)

    def acquire_bigkinds(self) -> None:
        with get_client(sync_client=True) as client:
            limit = client.read_global_concurrency_limit_by_name(
                self._settings.bigkinds_rate_limit_name
            )
        if not limit.active or limit.limit != 1 or limit.slot_decay_per_second <= 0:
            raise RequestStoppedError("빅카인즈 요청 속도 제한 비활성 또는 설정 오류")
        rate_limit(
            self._settings.bigkinds_rate_limit_name,
            timeout_seconds=self._settings.rate_limit_timeout_seconds,
            strict=True,
        )
