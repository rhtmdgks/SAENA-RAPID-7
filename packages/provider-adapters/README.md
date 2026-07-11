# packages/provider-adapters

## Purpose

Engine/provider adapter boundary. Core must not depend on a single engine.

## Scope

chatgpt-search (primary), google-generative-search (PLANNED), gemini (PLANNED).

## Current decision

CONFIRMED adapter separation; v1 activates ChatGPT Search only.

## Constraints

- Feature flags / scale 0 for non-ChatGPT in v1\n- No optimize/observe/claim for Google/Gemini in v1

## Open decisions

- Exact interface module layout — PROPOSED names below

## Source specification references

- Algorithm §0, §6.1; k3s feature flags

## Status

Boundary CONFIRMED / adapters NOT IMPLEMENTED
