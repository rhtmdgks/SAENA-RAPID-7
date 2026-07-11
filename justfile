# SAENA RAPID-7 task runner (ADR-0010). `just verify` == the CI gate set;
# keep the two in lockstep (drift violates ADR-0018).
# just is provided by the dev group (rust-just, pinned in uv.lock):
#   uv run just <recipe>   — no host-global install required.

set shell := ["sh", "-c"]

default:
    @just --list

# One-time / after dependency changes
setup:
    uv sync --locked

lint:
    uv run ruff check .
    uv run ruff format --check .

typecheck:
    uv run mypy

test:
    uv run pytest -q

# Module boundary contracts (dependency-policy rule 11 / ADR-0002)
boundaries:
    uv run lint-imports

# Validate all contract schemas. Honest when empty: reports the count.
contracts-validate:
    @count=$(find packages/contracts -name '*.schema.json' 2>/dev/null | wc -l | tr -d ' '); \
    if [ "$count" = "0" ]; then \
        echo "contracts-validate: no *.schema.json under packages/contracts yet (W1 delivers schemas) — nothing validated"; \
    else \
        find packages/contracts -name '*.schema.json' -print0 | xargs -0 uv run check-jsonschema --check-metaschema; \
    fi

# Local gate — mirrors CI (ADR-0018)
verify: lint typecheck test boundaries contracts-validate
    @echo "verify: all local gates green"

# Worktree lifecycle (ADR-0023)
worktree-create unit +args:
    sh tools/development/worktree.sh create {{unit}} {{args}}

worktree-destroy unit:
    sh tools/development/worktree.sh destroy {{unit}}

worktree-audit:
    sh tools/development/worktree.sh audit

# Tier-2 local profile (defined W0, used from W2A — ADR-0022)
dev-up +services:
    @test -f tools/development/docker-compose.dev.yaml || { echo "dev-up: tools/development/docker-compose.dev.yaml not present yet (T15/W2A)"; exit 1; }
    docker compose -f tools/development/docker-compose.dev.yaml up -d {{services}}
