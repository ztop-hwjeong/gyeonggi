import asyncio

from prefect.blocks.system import Secret
from prefect.exceptions import ObjectNotFound
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AnalysisInitializationSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", hide_input_in_errors=True)

    openai_api_key: SecretStr = Field(min_length=1)
    openai_api_key_block: str = Field(default="openai-api-key", min_length=1)


async def initialize(settings: AnalysisInitializationSettings) -> None:
    value = settings.openai_api_key.get_secret_value()
    if not value:
        raise ValueError("OPENAI_API_KEY 설정 필요")
    try:
        existing = await Secret.aload(settings.openai_api_key_block)
    except ValueError as error:
        if not isinstance(error.__cause__, ObjectNotFound):
            raise
        await Secret(value=SecretStr(value)).asave(settings.openai_api_key_block)
    else:
        current = existing.get()
        if isinstance(current, SecretStr):
            current = current.get_secret_value()
        if current != value:
            raise RuntimeError("기존 OpenAI Secret과 환경 설정 불일치")
    print("OpenAI 분석 Secret 등록 확인")


if __name__ == "__main__":
    asyncio.run(initialize(AnalysisInitializationSettings.model_validate({})))
