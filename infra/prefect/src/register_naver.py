import asyncio
import json

from prefect.blocks.system import Secret
from prefect.client.orchestration import get_client
from prefect.client.schemas.actions import GlobalConcurrencyLimitCreate
from prefect.exceptions import ObjectNotFound
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class NaverInitializationSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", hide_input_in_errors=True)

    client_id: SecretStr = Field(validation_alias="X-NCP-APIGW-API-KEY-ID", min_length=1)
    client_secret: SecretStr = Field(validation_alias="X-NCP-APIGW-API-KEY", min_length=1)
    naver_credentials_block: str = Field(min_length=1)
    naver_rate_limit_name: str = Field(min_length=1)
    naver_request_interval_seconds: float = Field(default=3, gt=0)


async def initialize(settings: NaverInitializationSettings) -> None:
    value = {
        "client_id": settings.client_id.get_secret_value(),
        "client_secret": settings.client_secret.get_secret_value(),
    }
    block = Secret(value=SecretStr(json.dumps(value)))
    await block.asave(settings.naver_credentials_block, overwrite=True)
    async with get_client() as client:
        try:
            await client.read_global_concurrency_limit_by_name(settings.naver_rate_limit_name)
        except ObjectNotFound:
            await client.create_global_concurrency_limit(
                GlobalConcurrencyLimitCreate(
                    name=settings.naver_rate_limit_name,
                    limit=1,
                    slot_decay_per_second=1 / settings.naver_request_interval_seconds,
                )
            )
    print("네이버 API 인증 정보 및 공통 요청 제한 등록 완료")


if __name__ == "__main__":
    asyncio.run(initialize(NaverInitializationSettings.model_validate({})))
