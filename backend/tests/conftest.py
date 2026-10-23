from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from config import Settings
from container import create_container
from main import create_app


@pytest.fixture
def template_directory() -> Path:
    return Path(__file__).resolve().parents[1] / "templates"


@pytest.fixture
def client(template_directory: Path) -> Iterator[TestClient]:
    settings = Settings.model_validate(
        {
            "database_host": "unused.invalid",
            "database_port": 5432,
            "database_name": "test",
            "database_user": "test",
            "database_password": "test",
            "template_directory": template_directory,
        }
    )
    with TestClient(create_app(create_container(settings))) as client:
        yield client


@pytest.fixture
def report_input() -> dict:
    return {
        "analysis_date": "2026-10-29",
        "issues": [{"title": "정책 이슈", "keywords": "a, b"}],
        "articles": [
            {
                "number": 1,
                "keywords": "a, b",
                "publisher": "언론사",
                "title": "기사",
                "sentiment": "긍정",
                "reason": "분류 사유",
            }
        ],
    }
