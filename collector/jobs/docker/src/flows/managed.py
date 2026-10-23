from typing import cast
from uuid import UUID

from collector_storage.config import DatabaseSettings, ObjectStorageSettings
from collector_storage.objects import ObjectCredentials, RawObjectStore
from prefect import flow
from prefect.blocks.system import Secret
from prefect.context import FlowRunContext
from pydantic import SecretStr

from control.models import CollectionCancelled, ControlSettings
from control.repository import ControlRepository
from flows.collection import collect_bigkinds, collect_naver_request
from sources.naver.config import NaverCredentials, NaverSettings


def control_repository() -> ControlRepository:
    database = DatabaseSettings.model_validate({})
    password = cast(Secret, Secret.load(database.database_password_block)).get()
    return ControlRepository(database, SecretStr(cast(str, password)))


@flow(name="managed-collection", persist_result=False)
def managed_collection(request_id: UUID) -> None:
    context = FlowRunContext.get()
    if context is None or context.flow_run is None:
        raise RuntimeError("Prefect flow 실행 문맥 필요")
    repository = control_repository()
    request = repository.start(request_id, context.flow_run.id)
    if request is None:
        return
    try:
        storage = ObjectStorageSettings.model_validate({})
        credentials = cast(Secret, Secret.load(storage.credentials_block)).get()
        with RawObjectStore(storage, ObjectCredentials.model_validate(credentials)) as objects:
            if request.source == "bigkinds":
                status, summary = collect_bigkinds(request, repository, objects, ControlSettings())
            else:
                settings = NaverSettings.model_validate({})
                naver_credentials = cast(Secret, Secret.load(settings.credentials_block)).get()
                status, summary = collect_naver_request(
                    request,
                    context.flow_run.id,
                    repository,
                    objects,
                    settings,
                    NaverCredentials.model_validate(naver_credentials),
                )
        repository.finish(request_id, status, summary)
    except CollectionCancelled:
        repository.finish(request_id, "cancelled", {})
    except Exception as error:
        repository.finish(request_id, "failed", {}, type(error).__name__)
        raise
