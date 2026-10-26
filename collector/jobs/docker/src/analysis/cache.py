import asyncio
from hashlib import sha256

from langchain_core.caches import RETURN_VAL_TYPE, BaseCache
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Engine

from analysis.tables import response_cache


class PostgresResponseCache(BaseCache):
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.hit = False
        self.pending: tuple[str, str, list[dict]] | None = None

    @staticmethod
    def key(prompt: str, llm_string: str) -> str:
        return sha256((prompt + "\x00" + llm_string).encode("utf-8")).hexdigest()

    def lookup(self, prompt: str, llm_string: str) -> RETURN_VAL_TYPE | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(
                        response_cache.c.prompt,
                        response_cache.c.llm_string,
                        response_cache.c.generations,
                    ).where(response_cache.c.cache_key == self.key(prompt, llm_string))
                )
                .mappings()
                .first()
            )
        if row is None or row["prompt"] != prompt or row["llm_string"] != llm_string:
            return None
        self.hit = True
        return [
            ChatGeneration(
                message=AIMessage.model_validate(item["message"]),
                generation_info=item["generation_info"],
            )
            for item in row["generations"]
        ]

    def update(self, prompt: str, llm_string: str, return_val: RETURN_VAL_TYPE) -> None:
        generations = []
        for generation in return_val:
            if not isinstance(generation, ChatGeneration) or not isinstance(
                generation.message, AIMessage
            ):
                raise ValueError("채팅 분석 결과만 캐시 가능")
            generations.append(
                {
                    "message": generation.message.model_dump(mode="json"),
                    "generation_info": generation.generation_info,
                }
            )
        self.pending = (prompt, llm_string, generations)

    def commit(self) -> None:
        if self.pending is None:
            return
        prompt, llm_string, generations = self.pending
        with self.engine.begin() as connection:
            connection.execute(
                insert(response_cache)
                .values(
                    cache_key=self.key(prompt, llm_string),
                    prompt=prompt,
                    llm_string=llm_string,
                    generations=generations,
                )
                .on_conflict_do_nothing(index_elements=[response_cache.c.cache_key])
            )
        self.pending = None

    async def acommit(self) -> None:
        await asyncio.to_thread(self.commit)

    def clear(self, **kwargs: object) -> None:
        with self.engine.begin() as connection:
            connection.execute(delete(response_cache))
