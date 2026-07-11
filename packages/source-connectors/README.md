# packages/source-connectors

## Purpose

Connectors for Git/zip customer source intake.

## Scope

Read-only default; write/PR credentials leased post-approval.

## Current decision

PROPOSED package. Standardize Git App vs deploy key vs zip — OPEN DECISION (design §13).

## Constraints

- Never store long-lived customer creds in images\n- Secret scan before agent context

## Open decisions

- Intake standard — OPEN DECISION

## Source specification references

- Algorithm §6.2 repository-intake; design §13.3

## Status

NOT IMPLEMENTED
