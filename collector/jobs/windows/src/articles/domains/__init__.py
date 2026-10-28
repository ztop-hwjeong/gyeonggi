from urllib.parse import urlsplit

from articles.domains.base import DomainBodyPolicy
from articles.domains.kbs import KbsBodyPolicy

_POLICIES: tuple[DomainBodyPolicy, ...] = (KbsBodyPolicy(),)
_BY_HOST = {host: policy for policy in _POLICIES for host in policy.hosts}


def get_body_policy(url: str) -> DomainBodyPolicy | None:
    return _BY_HOST.get(urlsplit(url).hostname or "")
