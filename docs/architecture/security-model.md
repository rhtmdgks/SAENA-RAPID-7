# Security model

## Purpose

Security boundaries for agents, network, secrets, supply chain.

## Scope

Four safety gates, NetworkPolicy, secret lifecycle, prompt-injection model.

## Current decision

**CONFIRMED** gates: Input / Plan / Execution / Release.  
**CONFIRMED** default-deny NetworkPolicy; non-root Jobs; short-lived tokens.  
**CONFIRMED** deployment credentials never in FORGE.

## Four gates

| Gate | On failure |
|---|---|
| Input Gate | isolate/stop run |
| Plan Gate | B부서 re-review |
| Execution Gate | block command |
| Release Gate | isolate patch; forbid PR artifact promotion |

## Agent rules

- Plan Mode: read-only
- Execution: Action Contract scope only
- Critics: read-only
- Untrusted content never becomes instructions

## Constraints

- Least privilege RBAC; default SA has no API power
- SBOM + signature + pinned third-party skills
- Agent deny patterns include deploy/push/kubectl apply/terraform apply

## Open decisions

- ChatGPT observation account/ToS owner — OPEN DECISION (design §13)
- External egress policy details per environment — OPEN DECISION

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §5.4–5.5, §10
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §6, §10
- `SECURITY.md`

## Status

CONFIRMED model / NOT IMPLEMENTED controls
