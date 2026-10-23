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

실행 전에 `backend/.env.example`의 항목을 채워 `backend/.env`로 저장하거나 동일한 이름의 환경변수를 지정한다. 환경변수가 파일보다 우선하며 DB 접속 설정을 누락하면 앱 시작 시 오류가 발생한다. Prefect 모니터링에는 `PREFECT_API_URL`이 필요하며 로컬 서버 주소는 `http://127.0.0.1:4200/api`다.

## 키워드와 수집 요청

DB에는 `infra/postgres/migrations`의 SQL을 번호순으로 적용한다.

| API | 용도 |
| --- | --- |
| `GET /sources` | 채널과 기간 수집 지원 여부 |
| `GET /keyword-rules`, `POST /keyword-rules` | 검색 규칙 목록과 등록 |
| `GET /keyword-rules/{id}`, `PUT /keyword-rules/{id}` | 규칙 조회와 버전 확인 후 수정 |
| `GET /keyword-rules/{id}/versions` | 변경 당시 조건 이력 |
| `POST /collection-previews` | 저장 전 조건의 비동기 미리보기 요청 |
| `POST /collection-runs` | 저장한 규칙의 증분·과거 수집 요청 |
| `GET /collection-runs`, `GET /collection-runs/{id}` | 요청 목록과 진행 상태 |
| `POST /collection-runs/{id}/cancel` | 대기 요청 취소 또는 진행 중 취소 요청 |
| `GET /collection-runs/{id}/items` | 요청에서 확보한 목록과 미리보기 샘플 |

수정에는 조회한 `version`을 함께 보낸다. 충돌 시 `409`로 최신 내용 재확인을 요청한다.
미리보기·수집 생성에는 UUID 형식의 `Idempotency-Key` 헤더가 필요하다.
같은 키와 조건의 재요청은 기존 요청을 반환하며 다른 조건의 재사용은 거절한다.
수집 요청에는 규칙 버전과 조건을 고정해 보관한다. 이후 규칙 수정은 기존 요청에 반영되지 않는다.
신규 규칙은 정기 수집이 꺼진 상태로 등록된다. 네이버 검색은 기간 지정 과거 수집을 지원하지 않는다.

## 수집 모니터링

| API | 제공 정보 |
| --- | --- |
| `GET /monitoring/metrics` | 기사 상세 실행·처리·확보·실패 건수, 성공률, 단계별 시도, HTTP 오류, 원본 응답 개수·바이트 |
| `GET /monitoring/runs` | 빅카인즈 목록·기사 상세 Prefect 실행 목록과 상세 수집 진행 상태 |
| `GET /monitoring/runs/{run_id}` | 실행 상태·시작·종료·경과 시간, 상태 메시지, 저장된 상세 수집 진행 상태 |
| `GET /monitoring/runs/{run_id}/articles` | 실행 내 처리 완료한 기사의 확보 상태와 최종 수집 경로 |
| `GET /monitoring/errors` | 기사 상세 단계별 실패·검증 거절 사유, HTTP 상태, 이후 본문 확보 여부 |
| `GET /monitoring/workers` | Docker·Windows pool 상태, worker ONLINE/OFFLINE, 마지막 heartbeat |
| `GET /monitoring/search-metrics` | 네이버 목록의 조회·신규·갱신 건수, 원본 응답량, 당일 공통 요청 수 |
| `GET /monitoring/search-streams` | 채널·검색식별 마지막 성공 커서와 최근 실행 결과 |
| `GET /monitoring/runs/{run_id}/items` | 네이버 실행 당시의 정규화 목록 |

기간 조회는 기본 최근 24시간이며 `since`, `until`에 시간대가 있는 ISO 8601 시각을 지정한다.
기간은 최대 31일이며 목록은 `limit`(최대 200), `offset`으로 조회한다.
`runs`는 `state=FAILED` 또는 `state=CRASHED` 등 Prefect 상태로 필터링한다.
`errors`는 `run_id`, `stage`(`curl_cffi`, `browser_fetch`, `bigkinds_api`),
`recovered=true/false`로 필터링한다. `recovered=false`에는 아직 최종 결과가 없는 시도도 포함된다.

Prefect 실행 완료와 기사 확보 성공은 각각 `state`와 `collection`으로 구분한다.
빅카인즈 목록 실행은 Prefect 상태를 제공하며 `collection` 상세 집계는 없다.
네이버 목록 실행은 `collection`에 페이지·신규·갱신 건수와 커서 갱신 여부를 제공한다.
`search-metrics`는 실행 생성 시각 기준이며 `requests_today`는 조회 기간·채널과 무관한
한국 시각 당일의 네이버 검색 공통 요청 수다. `search-streams`는 오래된 커서도 확인할 수
있도록 기간 필터 없이 `channel`, `limit`, `offset`으로 조회한다.
`metrics`는 `scope=article_details`이며 실행 생성 시각을 기준으로 집계한다.
원본 응답 개수·바이트는 응답 저장 시각을 기준으로 하며 RustFS의 실제 디스크 사용량을 뜻하지 않는다.
성공률은 처리 완료한 기사 중 확보한 비율(0~1)이며 처리 결과가 없으면 `null`이다.
같은 기사의 재수집은 실행별 처리 건수에 포함한다. 중간 단계의 실패를 최종 기사 실패로 세지 않는다.
`last_completed_run_at`은 조회 기간과 무관한 마지막 상세 수집 완료 시각이다.

조회 실패는 503, 없는 수집 실행은 404, 잘못된 조회 조건은 422를 반환한다.
응답에 실행 매개변수·원본 HTML·인프라 자격 증명을 포함하지 않는다.
Prefect REST 계약은 [공식 API 문서](https://docs.prefect.io/v3/api-ref/rest-api/server/flow-runs/count-flow-runs)를 따른다.
대상 flow·pool은 `MONITORING_FLOW_NAMES`, `MONITORING_POOL_NAMES`의 JSON 배열로,
요청 제한 시간은 `MONITORING_TIMEOUT_SECONDS`로 설정할 수 있다.

## Excel 템플릿

`templates/{code}/{version}/`에 `template.xlsx`와 `manifest.json`을 함께 Git으로 관리한다.
메타데이터에는 코드, 이름, 버전, 파일명, SHA-256과 순서대로 나열한 시트 코드·이름을 지정한다.
`variables`는 JSON Schema Draft 2020-12로 변수의 타입·설명·필수 항목을 정의한다.
날짜는 `string` 타입과 `date` 형식, 목록은 `array`와 `items`의 객체 속성으로 표현한다.
시트 코드는 업무 식별자이며 시트 이름은 Excel의 실제 탭 이름이다.
배포한 버전은 유지하고 파일·수식·시트 구성이 바뀌면 새 버전을 추가한다.
템플릿 위치는 `TEMPLATE_DIRECTORY` 환경변수로 지정할 수 있다.

- `GET /templates`: 등록된 모든 템플릿 버전 조회
- `GET /templates/{code}/versions`: 특정 템플릿의 버전 목록 조회
- `GET /templates/{code}/versions/{version}`: 파일·시트 메타데이터 조회
- `GET /templates/{code}/versions/{version}/file`: 원본 템플릿 다운로드
- `POST /templates/{code}/versions/{version}/render`: 입력 데이터로 Excel 보고서 생성
- `POST /templates/archive`: 선택한 템플릿 버전들의 ZIP 다운로드

항상 버전을 명시하며 템플릿 관리는 Git 변경으로 진행한다.
보고서 생성 시에는 선택한 버전의 복사본에 값을 입력하며, 보관 중인 템플릿을 수정하지 않는다.

여러 Excel 양식은 각자 코드·버전으로 독립 관리한다. 한 Excel 파일 안의 시트들은 같은
템플릿에 속한다. ZIP은 아래 요청으로 만들며 각 파일과 메타데이터를 `{code}/{version}/`에
넣어 같은 파일명도 구분한다. 한 번에 최대 50개 버전을 선택할 수 있으며 중복 선택은 거부한다.

```json
{
  "templates": [
    {"code": "education-audit-press", "version": "1.0.0"}
  ]
}
```

### 템플릿 입력

Excel 안의 `{{analysis_date}}`는 단일 값, `#{{issues | noheader}}`와
`#{{articles | noheader}}`는 기존 머리글 아래에 표를 채우는 templexl 표기다.
표의 변수 이름은 입력 JSON의 배열 이름과 일치해야 한다.
manifest의 `tables`에는 DataFrame의 필드 순서를 명시한다. 셀 좌표와 종료 행은 지정하지 않는다.
반복 행의 서식과 수식은 Excel 템플릿에서 관리하며, 추가 행의 상대 수식은 엔진이 이동한다.

`render` API는 `{"data": {...}}` 형태의 JSON을 받는다. 예를 들어 다음과 같이 입력한다.

```json
{
  "data": {
    "analysis_date": "2026-10-29",
    "issues": [{"title": "교육 정책", "keywords": "폰프리, 학폭"}],
    "articles": [{
      "number": 1,
      "keywords": "폰프리",
      "publisher": "언론사",
      "title": "기사 제목",
      "sentiment": "긍정",
      "reason": "분류 사유"
    }]
  }
}
```

입력은 manifest의 JSON Schema로 검증하며 날짜 형식·필드 타입·필수 항목이 다르면 422를 반환한다.
기사는 1행 머리글 아래부터 채워진다. 원본 템플릿을 변경하지 않고 새 파일을 내려준다.
키워드는 `a, b`처럼 쉼표로 나누어 입력한다. 하나라도 포함되면 기사당 한 번 집계하며,
공백·빈 항목·중복 키워드는 집계 수를 늘리지 않는다. 다른 이슈에는 각각 중복 집계될 수 있다.
`issues`에는 개수 제한이 없으며 별도의 기타 분류를 사용하지 않는다.
쉼표 분리 집계 수식은 Microsoft 365 또는 Excel 2024 이상에서 사용한다.
파일 생성 자체는 Excel 설치가 필요 없고, 수식 결과는 Excel에서 열 때 재계산된다.
논조 비중은 제목이 입력된 전체 기사 수를 기준으로 하므로 미분류 기사가 있으면 합계가 100%보다 작다.

## 검증

```powershell
uv run pytest
uv run pyright
uv run ruff check .
uv run ruff format --check .
```
