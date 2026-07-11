#!/bin/sh
# SAENA RAPID-7 devcontainer post-create — ADR-0022.
# POSIX sh only; keep this fast and side-effect-limited (workspace setup only,
# no network calls beyond the lockfile-pinned `uv sync`).
set -eux

# git safe.directory — devcontainer bind-mounts the repo with a different
# owning UID than the image build; without this, git refuses to operate.
git config --global --add safe.directory /workspaces/*
git config --global --add safe.directory "$(pwd)"

# Install Python workspace deps from the committed lockfile only (ADR-0009 /
# ADR-0021 pinning: `uv sync --locked` fails closed on manifest/lockfile
# drift rather than silently re-resolving).
uv sync --locked

# Sanity check: confirm the dev-group `just` (pinned via uv.lock, ADR-0010)
# resolves and runs inside the workspace venv.
uv run just --version
