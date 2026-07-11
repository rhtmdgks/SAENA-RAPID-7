# evals/regression-suites

See ../README.md. NOT IMPLEMENTED — scaffold only (ADR-0007 D-7, 2026-07-12).

## 등재 스위트 (Wave 3 구현)

- Prompt pkg §12 회귀 세트 8종 (../README.md)
- k3s §10 failure-mode 9종 ↔ fixture 1:1 매핑
- **추출 아키텍처 테스트 (ADR-0002 rev.3 규칙 12)**: worker-hosted 모듈을 독립 배포로 분리해도 모듈 코드 변경 0 검증 — 경계 이벤트·published interface 규칙 위반 검출
