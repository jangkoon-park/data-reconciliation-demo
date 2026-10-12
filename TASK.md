# TASK

The original instructions for this repository, saved verbatim (Korean).

---

이 저장소에 데이터 정합성 검증(reconciliation) 데모를 만들어줘. 업워크 포트폴리오용이라 README는 영어로.

시나리오
- 가상 건설사의 원가 데이터: 현장(site), 계약(contract), 발주(order), 실적(actual)
- 원천 테이블과 그걸 집계한 리포트 테이블이 있고, 리포트 합계가 원천과 안 맞는 상황
- 실제 회사 데이터는 절대 쓰지 말고 전부 가상 데이터로 생성

구성
- PostgreSQL + Python(pandas, SQLAlchemy)
- 이 환경에서 PostgreSQL 설치가 안 되면 SQLite로 대체하고, README에 그 사실을 솔직하게 적을 것
- 일부러 불일치를 심어둘 것: 누락 행, 중복 행, 금액 반올림 차이, 잘못된 코드 매핑, 기간 경계 오류
- 대사 스크립트: 현장·계약 단위로 원천 vs 리포트 건수·금액 비교, 차이 원인을 유형별로 분류
- 결과 리포트: 불일치 목록과 원인 요약을 HTML 또는 Markdown으로 출력
- pytest로 검증 로직 테스트

범위 제한
- 데이터는 최대 10만 건, 같은 실험 반복 실행은 3회 이내

마무리
- README에 문제 상황, 접근 방법, 실행 방법, 결과 예시(표) 정리
- 이 지시 내용 전체를 TASK.md로 저장
- 브랜치에 push하고 무엇을 만들었는지 요약해줘
