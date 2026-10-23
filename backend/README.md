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
