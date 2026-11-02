from collections.abc import Callable
from urllib.parse import urlsplit

from articles.domains.ajunews import AjuNewsBodyPolicy, has_verified_official_photo_body
from articles.domains.asiae import AsiaeBodyPolicy
from articles.domains.asiatoday import AsiaTodayBodyPolicy
from articles.domains.base import DomainBodyPolicy
from articles.domains.busan import BusanBodyPolicy
from articles.domains.dnews import DnewsBodyPolicy
from articles.domains.etoday import ETodayBodyPolicy
from articles.domains.getnews import GetnewsBodyPolicy
from articles.domains.hankookilbo import HankookIlboBodyPolicy
from articles.domains.hankyung import HankyungBodyPolicy
from articles.domains.imaeil import IMAEILBodyPolicy
from articles.domains.incheonilbo import IncheonIlboBodyPolicy
from articles.domains.joongang import JoongangBodyPolicy
from articles.domains.joongboo import JoongbooBodyPolicy
from articles.domains.kado import KadoBodyPolicy
from articles.domains.kbs import KbsBodyPolicy
from articles.domains.kihoilbo import KihoIlboBodyPolicy
from articles.domains.kmib import KmibBodyPolicy
from articles.domains.kyeongin import KyeonginBodyPolicy
from articles.domains.mk import MkBodyPolicy
from articles.domains.naeil import NaeilBodyPolicy
from articles.domains.news1 import News1BodyPolicy
from articles.domains.newscj import NewscjBodyPolicy
from articles.domains.newsis import NewsisBodyPolicy
from articles.domains.newspim import NewsPimBodyPolicy
from articles.domains.nocut import NoCutBodyPolicy
from articles.domains.nocut import is_notice_only as is_nocut_notice_only
from articles.domains.ohmynews import OhmynewsBodyPolicy
from articles.domains.sbs import SbsBodyPolicy
from articles.domains.sedaily import SedailyBodyPolicy
from articles.domains.seoul import SeoulBodyPolicy
from articles.domains.shinailbo import ShinailboBodyPolicy
from articles.domains.thepublic import ThePublicBodyPolicy
from articles.domains.viva100 import Viva100BodyPolicy
from articles.domains.yonhap import YonhapBodyPolicy
from articles.models import ArticleSeed
from config import ExtractionSettings

_POLICIES: tuple[DomainBodyPolicy, ...] = (
    KbsBodyPolicy(),
    News1BodyPolicy(),
    ETodayBodyPolicy(),
    GetnewsBodyPolicy(),
    SedailyBodyPolicy(),
    SeoulBodyPolicy(),
    AjuNewsBodyPolicy(),
    BusanBodyPolicy(),
    DnewsBodyPolicy(),
    AsiaeBodyPolicy(),
    AsiaTodayBodyPolicy(),
    HankyungBodyPolicy(),
    HankookIlboBodyPolicy(),
    IMAEILBodyPolicy(),
    IncheonIlboBodyPolicy(),
    JoongbooBodyPolicy(),
    JoongangBodyPolicy(),
    KadoBodyPolicy(),
    KihoIlboBodyPolicy(),
    KmibBodyPolicy(),
    KyeonginBodyPolicy(),
    MkBodyPolicy(),
    NaeilBodyPolicy(),
    NewscjBodyPolicy(),
    NewsisBodyPolicy(),
    NewsPimBodyPolicy(),
    NoCutBodyPolicy(),
    OhmynewsBodyPolicy(),
    SbsBodyPolicy(),
    ShinailboBodyPolicy(),
    ThePublicBodyPolicy(),
    Viva100BodyPolicy(),
    YonhapBodyPolicy(),
)
_BY_HOST = {host: policy for policy in _POLICIES for host in policy.hosts}
_NOTICE_CHECKS: tuple[Callable[[str], bool], ...] = (is_nocut_notice_only,)
_SHORT_OFFICIAL_BODY_CHECKS = {
    host: has_verified_official_photo_body for host in AjuNewsBodyPolicy.hosts
}


def has_verified_short_official_body(
    seed: ArticleSeed, title: str, text: str, settings: ExtractionSettings
) -> bool:
    check = _SHORT_OFFICIAL_BODY_CHECKS.get(domain_host(str(seed.original_url or "")) or "")
    return check(seed, title, text, settings) if check else False


def has_notice_only_text(text: str) -> bool:
    return any(check(text) for check in _NOTICE_CHECKS)


def domain_host(url: str | None) -> str | None:
    if url is None:
        return None
    return (urlsplit(url).hostname or "").lower() or None


def get_body_policy(url: str) -> DomainBodyPolicy | None:
    host = domain_host(url)
    return _BY_HOST.get(host) if host else None
