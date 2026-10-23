# 경기교육 정책 홍보 분석

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Next.js와 TypeScript, FastAPI, PostgreSQL, Prefect. nginx를 통한 단일 진입점.

## Users

경기교육 정책의 언론·온라인 반응을 장기간 수집하고 운영하는 내부 담당자.

## Product Purpose

키워드와 수집 채널을 관리하고, 과거·정기 수집의 진행 상태와 결과, 실행 환경을 확인한다.

## Operating Context

운영 현황, 키워드 관리, 수집 실행, 수집 결과, 실행 환경을 왼쪽 메뉴로 탐색한다.
Docker의 목록 수집과 Windows의 브라우저 수집은 별도 실행 환경이다.

## Capabilities and Constraints

규칙 변경은 버전을 남기고 수집 요청은 당시 조건을 보존한다.
네이버 검색의 기간 수집 한계를 화면에 명시한다. 빈 데이터나 오류를 가상의 운영 수치로 대체하지 않는다.
개발 검증은 실제 수집을 실행하지 않는다.

## Brand Commitments

기존 BizLens 디자인 기준의 밝은 배경, 블루 강조, Pretendard, Phosphor 아이콘을 사용한다.

## Product Principles

- 초보자도 조건과 다음 행동을 이해할 수 있는 짧고 명확한 안내
- 요청 접수, 작업 완료, 자료 확보의 구분
- 미리보기와 정식 자료의 구분
- 오류 원인과 복구 행동의 연결
