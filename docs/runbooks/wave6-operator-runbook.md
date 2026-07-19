# Wave 6 operator runbook — Pilot / Skill Pack / External-Project Runner

## Purpose

Step-by-step operator procedure for a SAENA FORGE run on a **new computer**:
bootstrap the workstation, install the skill pack plugin, start Claude Code
from the RAPID-7 checkout, and drive `saena-pilot` against an **external
customer repository** — referenced, never copied.

Every command block below was exercised on 2026-07-19 (macOS, `claude` CLI
2.1.205, `uv` 0.11.8). Sample outputs are copied from real runs; the exact
command → exit-code log lives in the Wave 6 closure handoff. Where a command
could not be verified locally it is flagged **UNVERIFIED** with the reason.

## Scope

- Engine scope: **ChatGPT Search only** (NR-1). Google AI Overviews / AI Mode /
  Gemini are out of scope — do not observe, optimize, or claim on them.
- Invariant: **RAPID-7 never copies the customer repo.** The pilot references
  the customer path (`claude --add-dir <customer>`), and customer-side writes
  happen ONLY in a dedicated customer-side git worktree.
- Out of scope for the tooling and for the operator acting through it:
  production deploy, `git push` of customer work, CMS publish, DNS/live-robots
  changes, PR merge — those are human decisions (see §17).

## Authoritative references

- `docs/architecture/wave6-plan.md` — Wave 6 DAG, frozen interface contracts.
- `scripts/bootstrap-claude.sh` — workstation bootstrap.
- `tools/saena-pilot/src/saena_pilot/cli.py` — the 7 pilot modes + exit codes.
- `.claude-plugin/marketplace.json`, `plugins/saena-skill-pack/.claude-plugin/plugin.json`
  — skill-pack packaging.
- `.claude/skills/manifest.json` — the 16-skill SSOT.

---

## 1. New-computer setup — prerequisites

Install these first (each installer needs human approval under the ADR-0019
install policy; the bootstrap script never installs them for you):

- **git** — Xcode Command Line Tools (macOS) or the distro package (Linux).
- **uv** — from <https://docs.astral.sh/uv/>. Pinned version lives in
  `.tool-versions` (`uv 0.10.4` at baseline; a newer uv is reported as a WARN,
  not a failure). `uv` provisions the pinned Python (`3.12.x`) itself.
- **claude** — Claude Code CLI, from <https://claude.com/claude-code>.

Clone the repo and put the uv tool bin dir on PATH for this shell:

```sh
git clone https://github.com/SAENA-Labs/SAENA-RAPID-7   # or your remote
cd SAENA-RAPID-7
export PATH="$HOME/.local/bin:$PATH"                     # uv tool bin dir
```

## 2. Bootstrap the workstation — `scripts/bootstrap-claude.sh`

`--check` is read-only and mutates nothing (default). `--install` runs only
hook-allowlisted, version-pinned installs (`uv sync --locked`, `uv tool install
rust-just==<pin>`, optional `shellcheck-py`, and — when packaging is present —
the plugin install of §3). `--json` emits `saena.bootstrap-report/v1`.
Exit codes: `0` = no FAIL (WARN/N/A allowed), `1` = a FAIL check, `2` = usage.

```sh
sh scripts/bootstrap-claude.sh --help      # usage
sh scripts/bootstrap-claude.sh --check     # read-only verification (default)
sh scripts/bootstrap-claude.sh --install   # idempotent, pinned installs only
sh scripts/bootstrap-claude.sh --check --json   # machine-readable report
```

Real `--check` output on a synced workstation (exit 0):

```
SAENA RAPID-7 bootstrap-claude - mode: check
repo root: /path/to/SAENA-RAPID-7

CHECK              STATUS DETAIL
-----              ------ ------
repo-root          PASS   /path/to/SAENA-RAPID-7
git                PASS   git version 2.50.1 (Apple Git-155)
uv                 WARN   uv 0.11.8 on PATH; .tool-versions pins 0.10.4
python             PASS   python 3.12 interpreter available via uv (pin 3.12.8)
claude-cli         PASS   claude CLI 2.1.205 (Claude Code)
uv-sync            PASS   uv.lock present; .venv present (read-only check)
just               PASS   just 1.56.0 (pin 1.56.0)
shellcheck         PASS   shellcheck 0.10.0 (optional lint tool)
gitleaks           N/A    not installed locally; CI security.yml runs it
...
hook-scripts       PASS   all 5 W0 safety hook scripts present
agents             PASS   14 agent definitions present
skills-manifest    PASS   skill manifest present (.claude/skills/manifest.json)

Result: fail=0 warn=2 n/a=3 (exit 0)
```

Notes (honest): `gitleaks`/`kubectl`/`helm`/`k3d`/`oasdiff` are **report-only**
— the script never installs them and never claims a local scan/deploy check
ran; CI covers them. A newer-than-pinned `uv` is a WARN, not a FAIL. Sourcing
the script (`. scripts/bootstrap-claude.sh --check`) is safe — it never exits
or `cd`s the calling shell.

## 3. Plugin install / update / uninstall (user scope)

The skill pack ships as a Claude Code plugin. Its canonical source is
`.claude/skills/**`; `plugins/saena-skill-pack/` is the generated, byte-identical
installable copy (drift-gated by `tools/validation/skill_pack_sync.py`). All
commands are user-scope and verified (w6-09) with exit 0:

```sh
claude plugin marketplace add /path/to/SAENA-RAPID-7
claude plugin install saena-skill-pack@saena-rapid-7
claude plugin list
claude plugin update saena-skill-pack@saena-rapid-7
claude plugin uninstall saena-skill-pack@saena-rapid-7
claude plugin marketplace remove saena-rapid-7
```

Verified sample output:

```
✔ Successfully added marketplace: saena-rapid-7 (declared in user settings)
✔ Successfully installed plugin: saena-skill-pack@saena-rapid-7 (scope: user)

Installed plugins:
  ❯ saena-skill-pack@saena-rapid-7
    Version: 1.0.0
    Scope: user
    Status: ✔ enabled
```

`claude plugin validate . --strict` returns `✔ Validation passed` (exit 0).

**UNVERIFIED (GitHub form):** the shorthand
`claude plugin marketplace add SAENA-Labs/SAENA-RAPID-7` requires network,
auth, and a pushed branch — not exercised in this environment. Use the local
path form above until it can be verified against the published repo.

## 4. Start Claude Code from the RAPID-7 checkout

Always start from the repo root so `CLAUDE.md`, `.claude/agents/**`,
`.claude/hooks/**`, and the installed skills are authoritative:

```sh
cd /path/to/SAENA-RAPID-7
claude
```

The W0 safety hooks (deny-deploy-push, deny-unpinned-install, protect-paths,
audit-log, secret-scan) are wired in the checked-in `.claude/settings.json` and
active from session start. `saena-pilot` launches Claude from this same root
(cwd pinned) so those hooks stay active during a customer run.

## 5. Referencing the external customer repo — `saena-pilot`

`saena-pilot` is a workspace console script. Run it from inside the RAPID-7
checkout. The seven modes and required flags (wave6-plan §3.3):

```sh
uv run saena-pilot --help
uv run saena-pilot --version        # saena-pilot 0.1.0

# start modes require --customer-repo (ABSOLUTE) and --domain (https):
uv run saena-pilot --customer-repo "/abs/customer/path" --domain "https://customer.example" --mode audit
uv run saena-pilot --customer-repo "/abs/customer/path" --domain "https://customer.example" --mode implement --intake intake.json

# preflight / plan are also start modes:
uv run saena-pilot --customer-repo "/abs/customer/path" --domain "https://customer.example" --mode preflight
uv run saena-pilot --customer-repo "/abs/customer/path" --domain "https://customer.example" --mode plan --intake intake.json

# run-scoped modes operate on a recorded run id:
uv run saena-pilot --mode status                 # list all runs
uv run saena-pilot --mode status  --run-id <id>
uv run saena-pilot --mode verify  --run-id <id>
uv run saena-pilot --mode resume  --run-id <id>

# --dry-run renders the exact claude launch argv + env WITHOUT executing:
uv run saena-pilot --customer-repo "/abs/customer/path" --domain "https://customer.example" --customer-id acme --mode audit --dry-run
```

Exit codes (frozen): `0` ok, `1` validation failed, `2` usage, `3` contract
incomplete, `4` bundle invalid, `5` boundary violation, `6` runtime error.
`--json` is accepted by every mode for a machine-readable report.

The rendered launch is `claude --add-dir <customer-path>` from the RAPID-7 root
— structural argv (no shell interpolation), never a repo copy. Verified
`audit --dry-run` tail:

```
launch (dry-run — NOT executed):
  cwd:  /path/to/SAENA-RAPID-7
  argv: claude --add-dir /abs/customer/path
  env:  SAENA_PILOT_RUN_ID=<uuid>
  env:  SAENA_PILOT_MODE=audit
  env:  SAENA_PILOT_RUN_DIR=<home>/pilot-runs/<uuid>
```

## 6. Required customer inputs (intake / action contract)

A complete action contract (`saena.pilot-contract/v1`) is assembled ONLY from
explicit human inputs: CLI flags plus an optional `--intake <file.json>`.
`preflight`/`audit` run with an incomplete contract and list the open
questions; `plan`/`implement` are **refused** until the contract is complete
(exit 3). The eight required fields / intake keys:

| Field / intake key | Meaning |
|---|---|
| `customer_id` (or `--customer-id`) | customer/tenant id |
| `allowed_write_scope` | globs the pilot may modify (non-empty) |
| `protected_paths` | globs that must never be modified |
| `build_commands` | list, or literal `"auto-detect-pending"` |
| `test_commands` | list, or literal `"auto-detect-pending"` |
| `deployment_responsibility` | must be the literal `"human"` |
| `data_classification` | non-empty string |
| `observation_authorization` | exactly `{"authorized": <bool>, "owner": "<name>"}` |

Unknown intake keys are rejected fail-closed; secret-shaped values are refused
before the contract is serialized; the pilot never auto-fills tenant id, write
scope, consent, KPIs, or legal approval. Zero-secret example intake:

```json
{
  "customer_id": "acme",
  "allowed_write_scope": ["src/**", "public/**"],
  "protected_paths": [".github/**", "infra/**"],
  "build_commands": "auto-detect-pending",
  "test_commands": "auto-detect-pending",
  "deployment_responsibility": "human",
  "data_classification": "customer-confidential",
  "observation_authorization": {"authorized": false, "owner": "acme-legal"}
}
```

## 7. Preflight & audit (read-only by default)

`preflight` and `audit` never write the customer repo. They validate the
customer-repo boundary, enforce the 16-skill bundle, build the (possibly
incomplete) contract, run framework discovery + Docker preflight, and record an
evidence chain. `audit` additionally renders/executes a Claude launch (use
`--dry-run` to render without launching). Verified `preflight` excerpt:

```
saena-pilot preflight report — run <uuid>
  RAPID-7 HEAD:  <sha>
  customer HEAD: <sha>
  domain:        https://acme.example
boundary findings:
  (none)
skill bundle: saena-forge-core — 16 skill(s), manifest sha256 <hash…> (validated)
action contract: INCOMPLETE — open questions:
  1. What is the customer/tenant id for this pilot (--customer-id)?
  ...
discovery: framework=unknown status=UNKNOWN — package.json present but no
  recognized framework dependency ... (not guessed)
docker: cli_present=True daemon_healthy=True server_version=29.4.1
hooks: active — 5/5 scripts present, settings_present=True
```

## 8. Implement mode (isolated customer worktree)

`implement` is the **only** mode with customer-write capability, and only with a
COMPLETE contract. Writes go to a dedicated customer-side git worktree —
`<customer>.saena-worktrees/<run-id>` on branch `saena-pilot/<run-id>` — never
the customer's working tree, never a copy inside RAPID-7. `--dry-run` renders
the worktree path deterministically without creating it. Verified
`implement --dry-run` tail (contract COMPLETE):

```
action contract: COMPLETE
launch (dry-run — NOT executed):
  cwd:  /path/to/SAENA-RAPID-7
  argv: claude --add-dir /abs/customer/path.saena-worktrees/<uuid>
  env:  SAENA_PILOT_MODE=implement
```

Write modes BLOCK on a dirty tree, detached HEAD, or nested repos (read modes
WARN); the operator resolves those with the customer before implement.

## 9. Verification

```sh
uv run saena-pilot --mode verify --run-id <id>
```

Re-hashes and verifies the append-only evidence chain for the run:

```
evidence chain VERIFIED for run <uuid>: 7 record(s), head <hash…>
```

`--mode status --run-id <id>` also reports `evidence: VERIFIED` (or
`INVALID (...)` if the chain was tampered).

## 10. Resume / status

```sh
uv run saena-pilot --mode status                 # list run ids
uv run saena-pilot --mode status --run-id <id>   # full run record
uv run saena-pilot --mode resume --run-id <id>   # re-validate + continue
```

`resume` re-validates the boundary, re-enforces the bundle, and **refuses** if
the skill manifest changed since the run was recorded (start a fresh run).
Verified:

```
run <uuid> is RESUMABLE (state re-validated)
  last mode: audit
  next step: re-invoke saena-pilot --mode audit … or continue with the recorded worktree
```

## 11. Evidence locations

Run state lives OUTSIDE both repos (fail-closed guard). Default home is
`~/.saena`; override with `SAENA_PILOT_HOME`:

```
$SAENA_PILOT_HOME/pilot-runs/<run-id>/        # default: ~/.saena/pilot-runs/<run-id>/
  ├── contract.json      # the action contract (sha256 bound into evidence)
  ├── evidence.jsonl      # append-only, sha256-chained event log
  ├── report.json         # machine-readable run report
  └── report.txt          # human report
```

Each evidence record binds `rapid7_sha`, `customer_sha`, `domain`, `mode`,
`run_id`, `manifest_schema_version`, `manifest_sha256`, and the skill bundle
names — the provenance chain for the run.

## 12. Rollback

- **RAPID-7 side:** the pilot never mutates the RAPID-7 checkout (only reads
  `git rev-parse`). Nothing to roll back here; if a run is abandoned, delete its
  `~/.saena/pilot-runs/<run-id>/` directory.
- **Customer side:** all customer edits are confined to the
  `<customer>.saena-worktrees/<run-id>` worktree on branch
  `saena-pilot/<run-id>`. To discard, remove the worktree and delete the branch
  (customer-side git operations, done by/with the customer). The customer's
  original working tree and default branch are never touched.
- Per-patch rollback units for in-run edits are the FORGE `saena-rollback`
  skill's responsibility (100% rollback-artifact SLO); the pilot itself performs
  no destructive customer git action.

## 13. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `must be run from inside the SAENA RAPID-7 checkout` | run `saena-pilot` from the repo root (a `.claude/` dir must be present). |
| exit 3, "action contract INCOMPLETE" | answer the listed questions via `--customer-id` + `--intake`. |
| exit 5, boundary violation | `--customer-repo` must be an ABSOLUTE path to a git repo root; resolve dirty/detached/nested state for write modes. |
| exit 4, bundle invalid | skill manifest/skills drifted — run `uv run python tools/validation/skill_bundle.py enforce`. |
| `resume` refused | the manifest changed since the run; start a fresh run. |
| `just`/`shellcheck` "installed but not on PATH" WARN | `export PATH="$HOME/.local/bin:$PATH"`. |
| plugin not found | `claude plugin marketplace add /path/to/SAENA-RAPID-7` then re-install. |

Skill-pack integrity checks (all exit 0 when healthy):

```sh
uv run python tools/validation/skill_manifest.py validate-manifest --manifest .claude/skills/manifest.json
uv run python tools/validation/skill_manifest.py validate-skills  --manifest .claude/skills/manifest.json --skills-root .claude/skills
uv run python tools/validation/skill_bundle.py enforce
uv run python tools/validation/skill_pack_sync.py check
```

## 14. Docker behavior (honest)

The pilot's lanes are **container-free** by design (fixture repos +
subprocess). Docker is only *probed* for preflight reporting — it is not
required to run the pilot. The report states the truth of the host:

```
docker: cli_present=True daemon_healthy=True server_version=29.4.1
# Docker-absent host reports cli_present=False / daemon_healthy=False honestly;
# the pilot continues (no container is launched by the pilot).
```

## 15. Limitations

- Engine scope is ChatGPT Search only; nothing here observes or optimizes
  Google AI Overviews / AI Mode / Gemini.
- Framework discovery is signal-scored and never guessed: an unrecognized repo
  yields `framework=unknown status=UNKNOWN`, and rendering defaults are labelled
  "framework default, not verified".
- Platforms: macOS + Linux tested. Windows is UNTESTED (expected to work under
  WSL `sh`, not native cmd.exe/PowerShell).
- The GitHub-shorthand marketplace form (§3) is UNVERIFIED here.
- The `claude plugin` install/list/update/uninstall commands and `claude plugin
  validate --strict` (§3) are verified on the author's macOS run with the local
  `claude` CLI; they are NOT reproduced in CI (the `claude` binary is absent
  there), where the enforcing layer is `skill_pack_sync.py check` (byte-equality
  drift) + the `tests/unit/skill_pack` lane.
- CI-side named gates for these commands ARE integrated: `.github/workflows/
  ci.yml` carries all 11 Wave 6 jobs (skill-manifest, skill-quality,
  skill-bundle-bypass, plugin-validate, claude-bootstrap, pilot-path-boundary,
  pilot-security, pilot-e2e, pilot-failure-modes, pilot-evidence-integrity,
  docs-consistency), each backed by a `justfile` recipe (`just verify-w6` runs
  them together).

## 16. What is / ISN'T automated

**Automated:** workstation bootstrap checks, pinned toolchain install, plugin
install/update, skill-bundle enforcement at every pilot start, customer-repo
boundary validation, contract assembly from explicit inputs, framework
discovery, Docker preflight probe, evidence chaining, launch rendering, resume
re-validation.

**NOT automated:** installing git/uv/claude (human-approved installers),
answering intake questions, authoring business claims/consent/KPIs, deciding
write scope, and everything in §17.

## 17. What still requires a human

- **Approval** — signing the Action Contract before any write.
- **Deploy / publish** — production deploy, CMS publish, DNS or live-robots
  changes are OUT OF SCOPE and hook-denied.
- **`git push` / PR merge** — the pilot never pushes customer work; merge is a
  human PR decision (CLAUDE.md #10).
- **ToS / legal** — observation authorization, data classification, and legal
  reconciliation of customer `CLAUDE.md`/`AGENTS.md` rules (stricter rule wins).

## 18. Zero-secret examples only

Every example on this page uses fixture paths (`/abs/customer/path`,
`/path/to/SAENA-RAPID-7`) and `*.example` domains. Never place real
credentials, tokens, or customer data in flags, intake files, or evidence —
secret-shaped intake values are refused fail-closed, and CI runs gitleaks over
full history.

## Status

IMPLEMENTED (2026-07-19) — every command block above verified by real
execution (w6-16). Docs-consistency CI enforcement is integrated as the
`docs-consistency` job in `.github/workflows/ci.yml` (w6-15).
