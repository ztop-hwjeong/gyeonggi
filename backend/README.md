# 경기교육 정책 홍보 분석 API

기사 수집 결과와 분류 검수, 통계 및 보고서 출력을 제공하는 백엔드다.

## 실행

저장소 루트에서 PostgreSQL을 시작한다.

```powershell
docker compose up -d postgres
```

`backend`에서 의존성을 설치하고 개발 서버를 실행한다.

```powershell
uv sync --locked
uv run uvicorn main:create_app --app-dir src --factory --reload
```

API 문서는 `http://127.0.0.1:8000/docs`에서 확인한다. `GET /health`는 서버 상태를 확인하며 `{"status": "ok"}`를 반환한다.

실행 전에 `backend/.env.example`의 모든 항목을 채워 `backend/.env`로 저장하거나 동일한 이름의 환경변수를 지정한다. 환경변수가 파일보다 우선하며 DB 접속 설정을 누락하면 앱 시작 시 오류가 발생한다.

## 검증

```powershell
uv run pytest
uv run pyright
uv run ruff check .
uv run ruff format --check .
```
