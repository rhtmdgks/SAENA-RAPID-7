# packages/schemas

## Purpose

JSON Schema artifacts (Action Contract, run-context, etc.).

## Scope

Protected path. Validates Plan/Execution artifacts.

## Current decision

CONFIRMED Action Contract schema requirement; files NOT IMPLEMENTED.

**거취 확정 (2026-07-12, 사용자 — W0)**: 본 디렉토리는 **파생 산출물(codegen artifacts) 전용**으로 유지한다. 수기 편집 계약 스키마의 유일한 SSOT는 `packages/contracts`(ADR-0011)이며, 여기에는 codegen이 생성한 타입/검증 산출물만 배치된다. 수기 파일 반입 = 리뷰 거부 사유.

## Constraints

- Human approval required flag immutable once signed
- 수기 편집 금지 — 원본은 `packages/contracts`, 생성 도구는 W1 codegen spike에서 확정 (ADR-0009/0011)

## Open decisions

- ~~Exact schema file layout~~ — 종결: 파생 전용 재정의(위). 생성물 배치 규칙은 W1 codegen 도구 확정 시 부속 결정

## 패키징 scaffolding 예외 (w1-03 기록, 실장은 w1-12)

"수기 편집 금지"(위 §Current decision·§Constraints)는 계약 스키마 **콘텐츠**(codegen이 생성해야 할 타입/검증 산출물 본체)에 적용되는 원칙이며, 파생물 컨테이너 자체를 성립시키는 **패키징 scaffolding**은 이 금지의 예외로 둔다. 구체적으로:

- `pyproject.toml`(본 패키지의 uv workspace member 선언 — 의존성·빌드 메타데이터) — codegen이 생성할 수 없는 패키지 정체성 정의이므로 수기 작성 대상.
- `py.typed`(PEP 561 마커 — 타입 정보 배포 신호, 내용 없는 빈 파일) — 마찬가지로 codegen 산출물이 아니라 패키지 구조 자체의 일부.

이 두 파일은 "생성물을 담는 그릇"을 세우는 장치이지 그릇 안의 내용물이 아니므로, 예외 없이 전체를 codegen 산출물로 규정하는 것은 codegen 도구가 애초에 실행될 위치를 만들 수 없게 만드는 순환 문제를 일으킨다. 따라서 이 두 파일에 한해 수기 편집을 허용한다 — 계약 타입/검증 로직 자체를 이 파일에 손으로 써 넣는 것은 여전히 금지(그것은 원 금지 원칙이 막는 대상 그대로).

**생성 모듈의 drift 게이트**: scaffolding 예외 밖의 모든 생성 모듈(codegen이 산출하는 실제 타입/검증 코드)은 다음을 강제한다 — (a) 전건 파일 최상단에 **GENERATED 헤더**(수기 편집 금지 경고 + 생성 출처·명령 기록)를 codegen 도구가 자동 삽입, (b) `just codegen-check`가 "현재 `packages/contracts`로 재생성한 결과와 커밋된 `packages/schemas` 산출물이 바이트 동일한가"를 확인하고 **불일치(drift) 시 CI fail**. 이 두 장치(scaffolding 예외 + drift 게이트)는 함께 성립한다 — scaffolding만 예외로 두고 drift 게이트가 없으면 생성물에 수기 수정이 조용히 섞여 들어가도 검출되지 않는다.

`just codegen-check`의 실제 recipe 배선·GENERATED 헤더 포맷·codegen 도구 확정은 **w1-12**(packages/schemas member 확립 unit)에서 실장한다 — 본 절은 그 실장이 지켜야 할 원칙만 w1-03에서 기록한다(선행 unit인 w1-02 codegen spike의 성패에 의존).

## Source specification references

- Algorithm §5.2; Prompt package §1

## Status

NOT IMPLEMENTED
