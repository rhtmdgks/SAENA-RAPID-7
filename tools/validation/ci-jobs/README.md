# tools/validation/ci-jobs/

## Purpose

CI job handoff convention (ADR-0018): `.github/workflows/**`, `.pre-commit-config.yaml`,
`CODEOWNERS`는 **Integrator 단독 소유**다. 다른 patch unit이 CI 잡을 추가·변경하려면
여기에 `<team>-<job>.yml` 조각(잡 단위 완결 YAML + 주석으로 needs/permissions/트리거 명시)을
제출하고, Integrator가 `ci.yml`/`security.yml`에 조립한다.

## Status

W0에서는 팀 조각이 ADR 본문(0016~0021)으로 대체 전달되어 Integrator가 직접 조립했다.
W1부터 신규 잡은 반드시 이 디렉토리 경유.
