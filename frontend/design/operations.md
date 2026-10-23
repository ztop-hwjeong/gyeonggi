# 운영 화면

모드: Operate. 디자인 기준은 `../DESIGN.md`와 기존 토큰을 따른다.

## Direction contract

THESIS: 분석 담당자가 매일 수집 상태를 확인하고 오류·미완료 기간에 대응하는 업무 화면.

OWN-WORLD: 밝은 회색 바탕과 흰 작업 표면, 주요 동작의 블루, Pretendard와 Phosphor.
불필요한 장식과 반복 배지 대신 여백과 정렬로 정보 구분.

STORY: 확인 필요 요청 찾기 → 요청 당시의 조건·확보 범위 확인 → 같은 채널·기간 또는 미완료 날짜 보충 요청 → 확인 완료 표시 → 자료 읽기. 키워드 편집·미리보기·자동 수집 설정은 검색 조건의 흐름으로 연결.

FIRST VIEWPORT: 왼쪽 고정 메뉴, 페이지 제목과 수집 이력 이동, 자동 수집 미설정·연결 문제·검토 전 오류의 다음 행동. 수집량 추이는 그다음 근거로 배치.
모바일은 접을 수 있는 메뉴와 세로 작업 흐름.

FORM: 기존 BizLens 기준을 확장한 운영 작업 공간. seed: none (unavailable).

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## 용어와 상태

사용자는 개발자가 아닌 분석 담당자다. 내부 기술 용어는 API·코드에서 유지하고, 화면에는 업무 용어를 사용한다.

| 내부 개념 | 화면 표현 |
| --- | --- |
| Rule | 검색 조건 |
| Schedule | 자동 수집 |
| Run | 수집 요청 / 수집 이력 |
| Worker / Pool | 수집 환경, 목록 수집 / 브라우저 수집 |
| Cursor / Incremental | 마지막 수집 이후 / 새 자료 수집 |
| Backfill | 기간 수집 |
| Version | 검색 조건 변경 이력 / 저장 기록 |
| Submitted | 수집 준비 중 |
| Partial | 일부 수집 · 미완료 날짜 확인 |

확인 완료 표시는 검토 여부이며 수집 성공·누락 해소를 뜻하지 않는다. 확인 필요 목록은 검토 전 오류·일부 수집을 대상으로 하고, 전체 이력에는 검토한 요청도 보존한다.
미확인 건수는 ‘—’, 검색 결과가 없는 경우만 0건으로 표시한다. 사이트에 요청하지 않은 상태에서 연결 상태만으로 수집 성공을 단정하지 않는다.
