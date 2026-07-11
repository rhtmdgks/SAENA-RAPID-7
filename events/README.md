# events/

## Purpose

Event catalog and schemas. Protected path.

## Scope

catalog/ + schemas/.

## Current decision

CONFIRMED recommended topics; schemas NOT IMPLEMENTED.

## Constraints

- Envelope fields mandatory
- No PII/secrets in payloads

## Open decisions

- ~~AsyncAPI vs proto events~~ — **확정 (ADR-0008/0011)**: AsyncAPI 3.0 + 공통 JSON Schema 2020-12, proto 이연. envelope 구체 규칙 = ADR-0013

## Source specification references

- Algorithm §6.3; k3s §4

## Status

NOT IMPLEMENTED
