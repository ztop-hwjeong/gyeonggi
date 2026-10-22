from collections.abc import AsyncIterator

from dishka import Provider, Scope, make_async_container, provide
from fastapi.testclient import TestClient

from main import create_app


def test_health_without_database() -> None:
    with TestClient(create_app(make_async_container())) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_app_shutdown_closes_app_scoped_resources() -> None:
    released = []

    class ResourceProvider(Provider):
        @provide(scope=Scope.APP)
        async def resource(self) -> AsyncIterator[str]:
            try:
                yield "resource"
            finally:
                released.append(True)

    container = make_async_container(ResourceProvider())
    with TestClient(create_app(container)) as client:
        assert client.portal is not None
        assert client.portal.call(container.get, str) == "resource"
        assert not released
    assert released == [True]
