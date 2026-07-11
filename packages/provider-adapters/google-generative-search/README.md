# google-generative-search adapter

## Purpose

Future Google generative search surface adapter.

## Scope

AI Overviews; AI Mode (spec 근거: Algorithm §0 명시 제외 대상의 어댑터 경계). 기타 항목(Google Search indexing, query fan-out, Search Console ingestion)은 spec 외 추측 확장(boot B7) — PROPOSED, 활성화 결정 시 재검토.

Spec 명칭 대응 (ADR-0001 §3): Algorithm §6.1 `google-ai-adapter` = 본 패키지, `gemini-adapter` = `packages/provider-adapters/gemini`.

## Current decision

**PLANNED** only. v1: feature flag OFF / do not optimize, observe, or claim results.

## Constraints

- No implementation code in bootstrap
- Activation requires separate re-approval (design)

## Open decisions

- Activation criteria — OPEN DECISION / deferred

## Source specification references

- Algorithm §0 explicit exclusion; k3s §12 deferred

## Status

PLANNED / NOT IMPLEMENTED
