# Prompt 4 — Human handoff / B부서 결과물

원본: `docs/specs/SAENA_B_Department_Agent_Prompt_Package_v1.md` §9 (verbatim). 실행 주체: `forge-console-api`가 artifacts 병합 자동 생성. B부서는 최종 수령·배포 판단만.

```text
Produce a concise SAENA FORGE HANDOFF REPORT for the B department.

Include only verified facts:
1. Run ID, customer, repo base commit, branch/worktree, exact target engine
   (ChatGPT Search only), run dates and policy version.
2. Approved business question clusters and the completed patch units.
3. Changed files, short rationale, claim/evidence IDs, and rollback command.
4. Deterministic QA status: build, tests, lint, links, schema, a11y,
   performance, fidelity, security.
5. Measurement setup: baseline cells, treatment/control definition, observation
   date, and the difference between technical completion and external outcome.
6. Known limitations, blocked items, and missing customer evidence.
7. Next B-department action: review patch / open PR / request fact verification /
   request customer deployment. Never say "deploy automatically".

Do not claim that ChatGPT will cite, rank, recommend, or convert because a patch
was generated. State only registered and observed outcomes.
```
