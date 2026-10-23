# 수집기 실행

브라우저 없는 작업은 `docker-collector` Docker pool, Edge가 필요한 작업은 `windows-collector` process pool에 배포한다. Worker 운영, Docker 작업 이미지, Prefect 초기화는 각각 독립적인 uv 프로젝트와 잠금 파일을 사용한다.

## 서버와 Docker worker

저장소 루트에서 실행한다.

```powershell
docker build -f collector/jobs/docker/Dockerfile -t gyeonggi-collector:local collector
docker compose --profile collector up -d --build
```

Prefect UI는 `http://127.0.0.1:4200`이다. 두 pool은 초기화 서비스에서 등록한다. Docker worker는 작업마다 별도 Linux 컨테이너를 생성한다. 작업 이미지는 `gyeonggi-collector:local`이며, 수집 코드를 수정하면 다시 빌드한다. Docker worker는 작업 컨테이너 생성을 위해 Docker 소켓을 사용한다.

로컬 단일 Prefect 서버의 메타데이터는 SQLite로 `.docker/prefect/server`에 보존하며 업무 PostgreSQL과 분리한다. 서버·background service를 여러 프로세스로 확장할 때는 전용 PostgreSQL DB와 Redis를 구성한다.

## Docker 작업 배포

`collector/jobs/docker`에서 실행한다.

```powershell
uv sync --locked
$env:PREFECT_API_URL = 'http://127.0.0.1:4200/api'
uv run prefect deploy --name docker-check
uv run prefect deployment run docker-runtime-check/docker-check --watch
```

## 빅카인즈 목록 수집

`collector/jobs/docker`에서 목록 flow를 배포한다.

```powershell
$env:PREFECT_API_URL = 'http://127.0.0.1:4200/api'
uv run prefect deploy --name bigkinds-list --no-prompt
```

Prefect UI에서 `bigkinds-collect-list/bigkinds-list`를 선택하고 다음 매개변수로 실행한다.
`search_key`는 빅카인즈 검색식이며, `start_date`와 `end_date`는 수집할 발행일 범위다.

```json
{
  "request": {
    "search_key": "폰프리 OR 폰프리스쿨",
    "start_date": "2026-06-01",
    "end_date": "2026-06-01",
    "page_size": 10,
    "max_pages": 2
  }
}
```

`page_size`는 검증한 1~10 범위다. `max_pages`를 생략하면 첫 페이지의 검색 건수를 기준으로 필요한 페이지를 순차 조회한다.
제한 때문에 일부만 받았거나 검색 건수가 바뀌면 결과 manifest를 `partial`로 표시한다.
검증용 제한 수집은 Prefect 실행이 성공해도 자료 상태가 `partial`일 수 있다.
`completed`는 해당 조회에서 건수와 고유 기사 수가 일치했다는 뜻이며, 소스의 전량 제공을
보장하는 의미는 아니다. 같은 페이지만 반복되거나 건수가 있는데 페이지가 비면 실패한다.
상세 페이지와 언론사 원문에는 요청하지 않으며, 목록의 `summary`는 본문이 아닌 요약이다.
`original_url`과 빅카인즈 고유 ID는 후속 언론사 원문 수집에 사용할 수 있다.

작업은 `curl_cffi`의 Chrome impersonation을 기본으로 사용한다. User-Agent만 임의로
지정하지 않고 브라우저 프로필에 맞는 기본 헤더와 TLS·HTTP 동작을 함께 사용한다.
`HTTP_IMPERSONATE`, `HTTP_TIMEOUT_SECONDS`, `HTTP_RETRIES`, `HTTP_RETRY_DELAY_SECONDS`,
`HTTP_RATE_LIMIT_TIMEOUT_SECONDS`는 Pydantic Settings로 검증한다.

빅카인즈 요청은 Prefect 전역 제한 `bigkinds-http`를 공유하며 기본 10초 간격이다.
초기화 서비스가 없는 제한만 생성하고 기존 운영 설정은 유지한다. 최초 생성 간격은
초기화 서비스의 `BIGKINDS_REQUEST_INTERVAL_SECONDS`, 이름은 `BIGKINDS_RATE_LIMIT_NAME`으로
설정할 수 있다. 이름을 바꾸면 작업 배포의 같은 환경변수도 함께 맞춘다.
제한이 없거나 비활성 상태면 요청하지 않는다. 401·403·429, 서버의 대기 지시와 접근 확인
화면은 재시도하지 않고 종료한다. 연결 오류·시간 초과·5xx만 제한적으로 재시도한다.

결과는 `gyeonggi-collector-data` Docker 볼륨의 `bigkinds/{flow_run_id}/`에 보존한다.
작업 컨테이너가 삭제되어도 남으며 worker에는 조회 목적으로 읽기 전용 연결한다.

- `raw/`: 페이지별 원본 응답과 검색 조건·해시
- `pages/`: 페이지별 정규화 목록
- `articles.jsonl`: 실행 내 고유 ID로 중복 제거한 목록
- `manifest.json`: 입력·프로필·실행 상태·조회 및 중복 건수

`COLLECTION_OUTPUT_DIRECTORY`와 `BIGKINDS_RATE_LIMIT_NAME`은 작업에 필요한 필수 설정이며
배포 YAML에 지정한다. 자동 주기는 없으며 요청한 기간만 실행한다. 원본 파일은 정규화가
실패해도 남는다. 실패한 실행의 자료는 manifest와 페이지 파일로 확인한다.

## Windows worker와 작업 배포

Edge와 uv가 설치된 Windows의 저장소 루트에서 실행한다.

```powershell
docker compose --profile collector up -d --build
```

`windows-worker`는 Compose의 `provider` 기능으로 Windows 호스트에서 실행한다. Compose는 2.36 이상이 필요하다. Worker와 Edge는 로그인한 사용자 세션에서 실행하며 터미널을 닫아도 유지한다. Worker 프로세스 종료 시 감시 프로세스가 10초 후 재시작한다. Edge 창은 작업 완료 후에도 유지하며, 작업이 없는 동안 닫혀도 3초 후 같은 프로필로 다시 연다. 작업은 로컬 CDP 주소 `http://127.0.0.1:9222`로 연결한다.

경로, 서버 주소, 프로필, pool과 동시 실행 수는 `windows-worker.provider.options`에서 지정한다. 실행 시 Pydantic Settings로 검증하며 필수 설정 누락이나 Edge 기본 프로필 사용은 프로세스 시작 전에 차단한다. 재시도 횟수와 대기 시간은 설정 모델의 기본값 또는 같은 이름의 환경변수로 관리한다.

```powershell
docker compose --profile collector down
```

`down`은 Windows 감시 프로세스와 자식 프로세스도 종료하므로 진행 중인 브라우저 작업을 마친 후 실행한다. 로그와 프로세스 식별 정보는 `.docker/prefect/windows-worker`에 보존한다. 감시 프로세스 자체 종료나 Windows 재부팅 후에는 `up`을 다시 실행한다. `restart: unless-stopped`는 컨테이너 서비스에만 적용된다.

작업을 배포할 때는 `collector/workers/windows`에서 실행한다.

```powershell
uv sync --locked
$env:PREFECT_API_URL = 'http://127.0.0.1:4200/api'
$env:COLLECTOR_DIRECTORY = (Get-Location).Path
$env:BROWSER_CDP_URL = 'http://127.0.0.1:9222'
uv run prefect deploy --name windows-check
```

별도 터미널에 같은 환경변수를 지정하고 점검 작업을 실행한다.

```powershell
uv run prefect deployment run windows-browser-check/windows-check --watch
```

Windows 점검은 관리 중인 Edge에 연결해 실행을 확인하고 연결만 해제한다. 실제 창이 필요한 worker는 로그인한 사용자 세션에서 실행한다. `.tmp/collector/profiles/edge`의 수집 전용 프로필을 사용하고 같은 프로필을 여러 작업이 동시에 사용하지 않는다. 다른 컴퓨터에서 실행하면 서버 주소와 작업 경로를 해당 환경에 맞게 지정한다.

점검 도중 Edge 창을 닫으면 감시 프로세스가 같은 프로필로 다시 열고 점검은 처음부터 재시도한다. 최초 실행을 포함해 최대 3회 시도하며 계속 닫히면 작업을 실패 처리한다. 작업 실패와 무관하게 Edge 감시·재실행은 계속 유지한다.

Edge 기본 사용자 프로필은 자동화 연결에 사용할 수 없다. 로그인은 수집 전용 프로필의 Edge 창에서 한 번 진행하며 이후 실행에서도 같은 프로필을 유지한다.

점검 배포에는 자동 스케줄이 없다. UI에서 pool별 worker ONLINE/OFFLINE, 마지막 heartbeat, 작업 상태와 로그를 확인한다. worker 생존 상태와 수집 성공 여부는 별도로 확인한다.

## 검증

Python 구현과 테스트가 있는 작업·Windows worker·Prefect 초기화 프로젝트에서 실행한다.

```powershell
uv sync --locked
uv run pytest
uv run pyright
uv run ruff check .
uv run ruff format --check .
```

Docker worker는 Prefect의 표준 CLI를 사용하며, `docker compose --profile collector build docker-worker`로 실행 이미지를 검증한다.
