import json
import os
from pathlib import Path


data_sources_path = Path("/workspace/GlobalConfiguration/.dbeaver/data-sources.json")


def needs_bootstrap() -> bool:
    if not data_sources_path.exists():
        return True

    source = json.loads(data_sources_path.read_text(encoding="utf-8"))
    connections = source.get("connections", {})
    folders = source.get("folders", {})

    if not isinstance(connections, dict) or not isinstance(folders, dict):
        raise ValueError("기존 data-sources.json 형식 오류")

    return not connections and not folders


if needs_bootstrap():
    password = os.environ.get("POSTGRES_PASSWORD")
    if not password:
        raise ValueError("POSTGRES_PASSWORD 설정 필요")

    data_sources_path.parent.mkdir(parents=True, exist_ok=True)
    data_sources_path.write_text(
        json.dumps(
            {
                "folders": {},
                "connections": {
                    "gyeonggi-postgres": {
                        "provider": "postgresql",
                        "driver": "postgres-jdbc",
                        "name": "경기교육 PostgreSQL",
                        "save-password": True,
                        "configuration": {
                            "host": "postgres",
                            "port": "5432",
                            "database": "gyeonggi",
                            "url": "jdbc:postgresql://postgres:5432/gyeonggi",
                            "configurationType": "MANUAL",
                            "type": "dev",
                            "auth-model": "native",
                            "auth-properties": {
                                "userName": "gyeonggi",
                                "userPassword": password,
                            },
                        },
                    }
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
