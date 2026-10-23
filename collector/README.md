# 수집기 실행

브라우저 없는 작업은 `docker-collector` Docker pool, Edge가 필요한 작업은 `windows-collector` process pool에 배포한다. Worker 운영, Docker 작업 이미지, Prefect 초기화는 각각 독립적인 uv 프로젝트와 잠금 파일을 사용한다.

## 서버와 Docker worker

저장소 루트에서 실행한다.

```powershell
& ./infra/rustfs/initialize-secrets.ps1
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
`provider_codes`에 빅카인즈의 언론사 코드 배열을 전달하면 해당 언론사만 검색한다.
생략하면 전체 언론사를 검색한다. 예: `"provider_codes": ["01100101"]`.
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

## 네이버 뉴스·블로그·카페글 목록

네이버 클라우드 NAVER API HUB의 검색 API를 사용한다.
저장소 루트 `.env`에 `X-NCP-APIGW-API-KEY-ID`, `X-NCP-APIGW-API-KEY`를 지정한다.
Compose의 `naver-init`은 두 값을 환경변수로 받아 Prefect Secret
`naver-api-hub-credentials`에 등록한다. 작업 배포에는 블록 이름만 지정한다.
키 변경 후에는 `docker compose --profile collector up -d --force-recreate naver-init`으로 갱신한다.

초기 DB 구성 후 `infra/postgres/migrations/002_search_collection.sql`을 적용한다.

```powershell
docker compose cp infra/postgres/migrations/002_search_collection.sql postgres:/tmp/002_search_collection.sql
docker compose exec -T postgres psql -U gyeonggi -d gyeonggi -v ON_ERROR_STOP=1 -f /tmp/002_search_collection.sql
```

Docker 작업 이미지를 빌드한 뒤 `collector/jobs/docker`에서 배포한다.

```powershell
$env:PREFECT_API_URL = 'http://127.0.0.1:4200/api'
uv run prefect deploy --name naver-news --name naver-blog --name naver-cafearticle --no-prompt
```

세 배포는 15분마다 실행한다. `parameters.request`에서 채널과 정책 검색어를 관리한다.
`terms`는 따옴표 없는 문구 배열이며 `"문구1" | "문구2"`로 합쳐 최신순으로 조회한다.
동일 문구를 중복 제거하고 순서를 정규화한다. 채널이나 검색식이 달라지면 별도 커서로 시작한다.
제목·요약의 강조 태그를 제거하며 뉴스 제공 시각과 블로그 작성일을 보존한다.
작성일을 주지 않는 카페글에는 수집 시각을 작성일로 대신 넣지 않는다.
목록 요약은 본문으로 취급하지 않으며 이 flow는 상세 URL에 요청하지 않는다.

최초 실행은 최신 첫 페이지로 커서를 초기화한다. 기본 50건이며 과거 전체 자료를 조회하지 않는다.
이후에는 날짜 내림차순으로 첫 페이지부터 이전 성공 커서의 모든 항목을 찾고 기본 1페이지를 더 확인한다.
뉴스·블로그는 이전 첫 페이지의 가장 오래된 게시 시점도 커서에 저장한다. 이전 ID가 없어도
페이지의 모든 날짜가 그 시점보다 `NAVER_DATE_OVERLAP_DAYS`(기본 1일) 이상 과거이면
날짜 경계 도달을 모니터링 정보에 기록하되 날짜만으로 수집 완료를 판정하지 않는다.
날짜가 없는 글도 저장하며, 날짜 누락 건수는 모니터링 정보에 기록한다.
날짜가 빠지거나 조회 순서가 역전되면 해당 실행의 날짜 판정을 중단한다.
날짜 없는 기존 커서는 다음 성공 시 날짜를 함께 저장하며, 작성일 없는 카페는 ID로 판정한다.
실행당 기본 50건씩 최대 20페이지, 최대 시작 위치 1000을 적용한다. 매번 20페이지를 모두 요청하지
않고 경계 확인 시 종료한다. 상한 안에서 경계와 겹침 구간을 확인하지 못하거나 페이지가
반복·비정상 응답이면 `partial`로 기록하고 커서를 유지한다. 다음 실행은 최신 첫 페이지부터
재확인하므로 상한을 넘는 장기 누적 구간의 수집 완료를 보장하지 않는다.
검색 결과에서 삭제된 커서 ID가 있다면 결과 끝을 확인하기 전까지 완료 처리하지 않는다.
완료한 페이지의 항목은 남으므로 재실행해도 같은 채널·URL을 중복 적재하지 않는다.
추가 검색어를 기존 커서의 완료 범위로 간주하지 않으며 같은 검색 스트림의 동시 실행은
PostgreSQL advisory lock으로 차단한다. 커서와 완료 상태는 같은 트랜잭션으로 반영한다.
삭제·재정렬·검색 색인 반영 지연과 API 조회 한도 때문에 전체 공개 글의 누락 없음을 보장하지 않는다.

검색 응답은 RustFS, 커서·실행·페이지 참조는 PostgreSQL `ops`·`st`, 정규화 목록은
`dw.search_items`에 보관한다. `st.search_run_items`로 실행 당시 목록을 추적한다.
다른 검색식에서 같은 항목을 찾더라도 채널·URL 기준으로 중복 제거한다.
페이지 상한을 늘려 재실행할 때는 요청량을 확인하고 배포 매개변수를 명시적으로 변경한다.

세 채널은 `naver-api-hub-http` 요청 제한과 `NAVER_DAILY_REQUEST_LIMIT` 예산을 공유한다.
기본 간격은 3초, 하루 예산은 한국 시각 기준 1,000회다. 연결 실패도 요청 예산에 포함하고,
실패한 HTTP 요청은 자동 재시도하지 않는다. 429·Retry-After 대기는 PostgreSQL에 보존해
다른 작업도 같은 대기 지시를 따른다. 운영 중인 전역 요청 간격은 초기화가 덮어쓰지 않는다.
상한·오류 상태는 Prefect 완료 여부와 별도로 `summary.status`, `cursor_advanced`로 확인한다.

API 계약: [뉴스](https://api.ncloud-docs.com/docs/naver-api-hub-search-news),
[블로그](https://api.ncloud-docs.com/docs/naver-api-hub-search-blog),
[카페글](https://api.ncloud-docs.com/docs/naver-api-hub-search-cafearticle).

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

UI에서 pool별 worker ONLINE/OFFLINE, 마지막 heartbeat, 작업 상태와 로그를 확인한다. worker 생존 상태와 수집 성공 여부는 별도로 확인한다.

## 기사 원문 수집과 원본 보존

`collector/jobs/windows`는 원문 수집과 본문 추출을 담당한다. 공통 HTTP 전송은
`collector/packages/http`를 사용하며 worker 운영 환경과 의존성을 분리한다.
`curl_cffi` 원문 요청 → 실제 Edge 탭의 `fetch()` → 기사 이동 후 렌더링 문서 →
빅카인즈 상세 API 순서로 시도한다. JavaScript로 본문을 생성하는 기사는 실제 페이지로
이동해 제목·본문 영역이 나타난 뒤 DOM을 보존하고 검증한다.
제목과 목록 요약의 일부 문장이 실제 본문에 일치하는지 검증하고 통과한 결과만 채택한다.
지면·웹 편집으로 문장이 달라진 경우에는 제목과 요약 전체의 유사도를 함께 비교해 인정한다.
판정에 사용한 유사도와 인정 사유는 추출 결과에 보존한다.
401·429·Retry-After는 같은 언론사에 브라우저로 반복 요청하지 않는다.
Edge 탭은 원문 사이트의 시작 화면으로 연결한 뒤 해당 출처에서 기사를 fetch한다.
작업 완료 후 창을 유지한다.

RustFS의 S3 API는 `http://127.0.0.1:9000`, 콘솔은 `http://127.0.0.1:9001`이다.
데이터는 `.docker/rustfs/data`, Compose 자격 증명 파일은 `.docker/rustfs/secrets`에 둔다.
`infra/rustfs/initialize-secrets.ps1`은 없는 자격 증명만 생성한다. 기존 파일을 덮어쓰지 않는다.
`rustfs-init`은 비공개 `collector-raw` 버킷과 Prefect Secret 블록
`collector-object-storage-credentials`를 등록하며 기존 자격 증명이 다르면 실패한다.
로컬 구성은 같은 자격 증명을 사용하므로 운영 배포 시 수집용 계정·버킷 권한을 분리한다.

응답 바이트는 문자 인코딩이나 HTML을 변경하지 않고 RustFS에 저장한다.
객체 키는 `articles/{run_id}/{stage}/{response_id}`이며, 같은 키를 덮어쓰지 않는다.
PostgreSQL의 `st.article_responses`에는 요청 대상·상태·객체 위치·크기·SHA-256을 기록한다.
원본을 읽을 때 크기와 해시를 검증한다. 객체 업로드 실패·누락·손상은 실행 실패로
표시하며 언론사에 재요청해 숨기지 않는다. 객체 업로드 후 DB 기록이 실패하면 객체만
남을 수 있으므로 백업·정리 시 DB 참조를 대조한다. 자동 만료는 설정하지 않는다.

`ops`에는 실행 상태와 언론사·호스트별 adaptive 특성 및 변경 이력,
`st`에는 수집 응답과 단계별 시도, `dw`에는 검증된 본문과 내용 버전을 보관한다.
adaptive 특성은 검증을 통과한 본문 요소만 갱신한다. 보존한 HTML과 추출 기록을
재사용하면 외부 요청 없이 본문을 다시 추출할 수 있다.
HTTP Content-Type과 HTML 인코딩 선언을 해석한 뒤 추출하며, 제목·본문의 문자 손실은 검증 실패로 처리한다.
수동으로 확인한 언론사 본문 구조에는 출처·canonical 기사 ID·제목·본문 요소와 검증 방식을
기록한다. 구조 확인만으로 빅카인즈 기사와 동일하다고 판정하지 않으며, 실제 수집에서도
제목·요약 검증을 계속 적용한다.

DB 초기 구성은 저장소 루트에서 다음과 같이 적용한다. DB와 RustFS 원본은 함께 백업하고 복구한다.

```powershell
docker compose cp infra/postgres/migrations/001_article_collection.sql postgres:/tmp/001_article_collection.sql
docker compose exec -T postgres psql -U gyeonggi -d gyeonggi -v ON_ERROR_STOP=1 -f /tmp/001_article_collection.sql
```

`collector/jobs/windows`에서 배포한다. DB 비밀번호는 환경변수 대신 지정한 Prefect Secret에
등록한다. 자격 증명 값은 배포 YAML이나 실행 매개변수에 넣지 않는다.

```powershell
uv sync --locked
$env:PREFECT_API_URL = 'http://127.0.0.1:4200/api'
$env:WINDOWS_JOB_DIRECTORY = (Get-Location).Path.Replace('\', '/')
$env:BROWSER_CDP_URL = 'http://127.0.0.1:9222'
$env:DATABASE_HOST = '127.0.0.1'
$env:DATABASE_PORT = '5432'
$env:DATABASE_NAME = 'gyeonggi'
$env:DATABASE_USER = 'gyeonggi'
$env:DATABASE_PASSWORD_BLOCK = 'collector-postgres-password'
$env:OBJECT_STORAGE_ENDPOINT_URL = 'http://127.0.0.1:9000'
$env:OBJECT_STORAGE_BUCKET = 'collector-raw'
$env:OBJECT_STORAGE_REGION = 'us-east-1'
$env:OBJECT_STORAGE_CREDENTIALS_BLOCK = 'collector-object-storage-credentials'
uv run prefect deploy --name article-details --no-prompt
```

`collect-article-details/article-details`의 `articles`에 목록 결과의 기사 배열을 전달한다.
원문 URL·소스 ID·언론사·제목·발행일·요약을 함께 전달해야 한다. 자동 주기는 배포하지 않는다.
한 실행 내 중복 ID는 거부하며 같은 내용의 본문은 DW에 중복 적재하지 않는다.
요청 간격, 응답 크기 제한과 본문 검증 임계값은 `DETAIL_`·`EXTRACTION_` 설정으로 관리한다.
요약이 너무 짧거나 제목·본문이 맞지 않으면 성공으로 취급하지 않는다.
언론사 본문 구조를 사전 검증할 때는 `allow_bigkinds_fallback=false`로 실행한다.
이 경우 원문 HTTP·브라우저 단계에서 검증하지 못한 기사를 빅카인즈 상세로 대체하지 않는다.
원문 추출 성공과 PostgreSQL adaptive 프로필 저장 여부를 함께 확인한다.

## 네이버 카페 상세 수집

`collector/jobs/windows`의 `naver-cafe-details` 배포는 저장된 카페 목록에서 본문 미수집 항목을
선택한다. 위 Windows 작업 환경변수를 지정한 뒤 다음 명령으로 배포·실행한다.

```powershell
uv run prefect deploy --name naver-cafe-details --no-prompt
uv run prefect deployment run collect-naver-cafe-details/naver-cafe-details --watch
```

DB에는 `infra/postgres/migrations`의 SQL을 번호순으로 적용한다.
카페 상세는 별도 주기 없이 실행하며 `NAVER_CAFE_BATCH_SIZE`(기본 10건)씩 처리한다.
수집 완료한 항목은 제외하고 실패 항목은 `NAVER_CAFE_RETRY_DELAY_MINUTES`(기본 60분) 후
다시 선택한다. 같은 카페 상세 흐름의 중복 실행은 PostgreSQL advisory lock으로 차단한다.

Edge 전용 탭을 실제 글 주소로 이동시키고 페이지가 자동 요청하는 상세 JSON 응답을 캡처한다.
글 본문을 별도로 HTTP 요청하지 않으며 탭·창은 유지한다. 카페·글 ID와 제목을 검증한 뒤
원본 JSON은 RustFS, 추출한 본문·작성 시각과 처리 상태는 기존 상세 수집 테이블에 저장한다.
텍스트 없는 이미지 글은 원본 응답을 보존하고 본문 추출 미완료로 남긴다.

글 이동 간격은 `NAVER_CAFE_REQUEST_INTERVAL_SECONDS`(기본 10초)로 전역 제한한다.
이미 존재하는 Prefect 전역 제한은 설정 변경으로 덮어쓰지 않는다.
401·403·429·Retry-After에서는 배치를 중단하고 대기 시각을 DB에 보존한다.
기본 대기는 `NAVER_CAFE_ERROR_PAUSE_SECONDS`(900초)이며 더 긴 Retry-After를 우선한다.
수집 실행·항목별 성공 및 실패·원본 응답은 기존 모니터링 API에서 확인한다.

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
