# 경기교육 정책 홍보 분석

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Next.js와 TypeScript, FastAPI, PostgreSQL, Prefect. nginx를 통한 단일 진입점.

## Users

경기교육 정책의 언론·온라인 반응을 분석하는 내부 담당자. 개발자가 아니며, 매일 수집 상태를 확인하고 오류·누락에 대응한다.

## Product Purpose

등록한 키워드 묶음에 관련된 자료를 찾아 읽고, 필요한 기간의 자료를 추가로 모은다. 수집 진행과 오류 확인은 자료를 확보하기 위한 보조 작업이다.

## Operating Context

키워드를 선택한 뒤 자료 읽기·수집 현황·키워드 설정을 같은 맥락에서 다룬다. 전체 수집 이력과 환경 점검은 보조 작업으로 제공한다.
Docker의 목록 수집과 Windows의 브라우저 수집은 별도 실행 환경이다.

## Capabilities and Constraints

규칙 변경은 버전을 남기고 수집 요청은 당시 조건을 보존한다.
네이버 검색의 기간 수집 한계를 화면에 명시한다. 빈 데이터나 오류를 가상의 운영 수치로 대체하지 않는다.
개발 검증은 실제 수집을 실행하지 않는다.

## Brand Commitments

기존 BizLens 디자인 기준의 밝은 배경, 블루 강조, Pretendard, Phosphor 아이콘을 사용한다.

## Product Principles

- 초보자도 조건과 다음 행동을 이해할 수 있는 짧고 명확한 안내
- 자료 제목을 눌러 읽는 한 가지 기본 동작과 최소한의 목록 정보
- 추가 조건과 설정은 필요할 때 열고, 기술적인 상태는 일반 자료 화면에서 생략
- 요청 접수, 작업 완료, 자료 확보의 구분
- 미리보기와 정식 자료의 구분
- 오류 원인과 복구 행동의 연결
