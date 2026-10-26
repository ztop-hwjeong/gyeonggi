# 경기교육 정책 홍보 분석

언론과 온라인 채널의 정책 키워드를 수집하고 운영 현황·결과·보고서를 관리하는 내부 서비스다.

- `frontend`: Next.js 운영 화면과 디자인 기준
- `backend`: FastAPI 업무 API와 Excel 템플릿
- `collector`: Docker·Windows 수집 작업과 Worker
- `infra`: nginx, PostgreSQL 마이그레이션과 Prefect 초기화

## 웹 실행

루트 `.env.example`을 참고해 `.env`에 DB 암호를 지정한다. 기존 DB를 사용하는 경우 기존 암호를 유지한다.

```powershell
docker compose up -d postgres
```

새 DB에는 `infra/postgres/migrations`의 SQL을 번호순으로 최초 한 번 적용한다.
기존 DB에는 아직 적용하지 않은 마이그레이션만 적용한다. 예를 들어 다음 명령으로 파일 하나를 적용한다.

```powershell
docker compose cp infra/postgres/migrations/001_article_collection.sql postgres:/tmp/migration.sql
docker compose exec -T postgres psql -U gyeonggi -d gyeonggi -v ON_ERROR_STOP=1 -f /tmp/migration.sql
```

웹과 API는 nginx를 통해 한 주소로 제공한다.

```powershell
docker compose up -d --build nginx
```

운영 화면은 `http://localhost:8080`, API 문서는 `http://localhost:8080/api/docs`다.
호스트 포트는 `APP_PORT`로 변경한다. 웹 실행은 수집 Worker를 시작하지 않는다.
CloudBeaver는 `http://localhost:8080/cloudbeaver/`에서 최초 관리자 설정 후 사용한다. 설정과 연결 정보는 `.docker/cloudbeaver`에 유지한다.
PostgreSQL 연결은 호스트 `postgres`, 포트 `5432`, 데이터베이스·사용자 `gyeonggi`, 기존 DB 암호로 설정한다.
수집 요청의 실제 실행과 원본 저장소 초기화는 [수집 운영 안내](collector/README.md)를 따른다.

각 앱의 개발·검증 명령은 [프론트엔드](frontend/README.md), [백엔드](backend/README.md)에 정리한다.
