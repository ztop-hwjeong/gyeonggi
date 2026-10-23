# 경기교육 정책 홍보 모니터링

키워드와 채널을 관리하고 수집 진행·결과·실행 환경을 확인하는 내부 웹 화면이다.
디자인 기준은 `DESIGN.md`를 따른다.

## 개발

```powershell
npm.cmd ci
npm.cmd run dev
```

개발 주소는 `http://localhost:3000`이다. `/api` 요청은 로컬 FastAPI의 8000 포트로 전달한다.
Compose에서는 nginx가 화면과 API를 같은 주소로 제공한다.
API 타입은 FastAPI의 OpenAPI 명세에서 생성한다. nginx로 API를 제공한 상태에서 명세 변경을 반영한다.

```powershell
npm.cmd run api:generate
npm.cmd run check
npm.cmd run build
npm.cmd run test:e2e
```

키워드는 같은 주제의 문구를 한 줄에 하나씩 등록한다. 정기 수집은 명시적으로 켠 규칙만 대상으로 한다.
미리보기와 수집 요청의 실제 실행에는 Prefect 배포와 연결된 Worker가 필요하다.
E2E 검증은 API 응답을 격리해 실제 수집을 요청하지 않는다.
처음 실행할 때는 `npx.cmd playwright install chromium`으로 검증용 브라우저를 설치한다.
