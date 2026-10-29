from urllib.parse import urlsplit

from articles.domains.base import DomainBodyPolicy
from articles.domains.kbs import KbsBodyPolicy

_POLICIES: tuple[DomainBodyPolicy, ...] = (KbsBodyPolicy(),)
_BY_HOST = {host: policy for policy in _POLICIES for host in policy.hosts}


def domain_host(url: str | None) -> str | None:
    if url is None:
        return None
    return (urlsplit(url).hostname or "").lower() or None


def get_body_policy(url: str) -> DomainBodyPolicy | None:
    host = domain_host(url)
    return _BY_HOST.get(host) if host else None
