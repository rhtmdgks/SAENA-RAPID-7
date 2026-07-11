# Provider interface candidates

## Purpose

Document shared interface candidates so core does not depend on a platform.

## Scope

Names only. **No interface source code** in bootstrap.

## Current decision

**PROPOSED** interface names (bootstrap requirement §5):

| Interface | Intent |
|---|---|
| CrawlerPolicy | robots/crawl eligibility & politeness |
| RetrievalEligibility | index/retrieval qualification checks |
| QueryGenerator | query/paraphrase/cluster generation hooks |
| ProbeRunner | controlled observation/probe execution |
| CitationExtractor | citation URL/normalization extraction |
| VisibilityScorer | layered visibility metrics (not single blob score) |
| TelemetryConnector | provider telemetry ingestion |
| OptimizationPolicy | provider-specific optimization constraints |

## Constraints

- Implementations live under provider folders
- Core/domain depends on these abstractions only (future)
- v1 concrete wiring: chatgpt-search only

## Open decisions

- IDL (TypeScript/Go/Protobuf) — OPEN DECISION

## Source specification references

- Bootstrap task §5; Algorithm provider adapter notes

## Status

PROPOSED / NOT IMPLEMENTED
