# SECURITY

## Purpose

보안 경계·보고·금지 사항 요약.

## Scope

SAENA FORGE package, agent runners, tenant isolation, supply chain.

## Current decision

CONFIRMED principles from k3s ops + harness design. Implementation NOT IMPLEMENTED.

## Constraints

- NetworkPolicy default-deny
- Non-root runners; short-lived credentials; TTL workspace destroy
- Secrets never in Helm values, ConfigMaps, image layers, prompts, audit payloads
- Production deployment credentials **never** registered in FORGE
- Customer Git starts read-only; write/PR token only after B approval + lease
- Untrusted web content quarantined; never treated as instructions
- Third-party skills: pinned SHA + SBOM + internal mirror only
- v1 engine: ChatGPT Search only; Google/Gemini adapters disabled

## Protected concerns

- AuthN/Z, tenant isolation, policy bundles
- `deploy/policies/**`, NetworkPolicy, RBAC
- Secret broker / workload identity

## Reporting

OPEN DECISION — internal security contact process not yet published.

## Source specification references

- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §6, §10
- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §5.4–5.5

## Status

CONFIRMED principles / NOT IMPLEMENTED controls
