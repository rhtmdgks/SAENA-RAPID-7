"""Engine-flag check — THE named W2C exit gate (k3s spec §8.1, condition 2:
"engine flags include any Google AI service in v1"; implementation-waves.md
W2C exit: "`forgectl preflight` 통과, Google flag on 시 fail 포함"; CLAUDE.md
Engine scope (v1): ChatGPT Search only, Google/Gemini disabled/forbidden).

The v1 closed enum is read from the generated pydantic artifact
(`saena_schemas.common.engine_id_v1.EngineId`) — the exact same source of
truth `saena_engine_gateway.registry.PERMITTED_ENGINE_IDS` uses — so this
check and the runtime engine gateway can never silently drift apart on
"what counts as permitted".

Values shape (k3s spec §7 skeleton):

```yaml
global:
  engineScope:
    chatgptSearch: true
    googleAiOverviews: false
    googleAiMode: false
    gemini: false
```

`engineScope` keys are camelCase Helm-values identifiers, not the
hyphenated `engine_id` wire values themselves — `_KNOWN_FLAG_KEYS` maps
every key this check recognizes to its canonical `engine_id` (or to `None`
for a key that is deliberately *not* a permitted v1 engine, e.g.
`googleAiOverviews`). Any `engineScope` key outside that map is itself
treated as a rogue/unrecognized engine-flag declaration and fails closed —
this check does not require an attacker to spell a key exactly one of the
four documented names to be caught; it fails on the *presence of an
unrecognized key* too, whether or not that key's value is `true`. This
mirrors `FlagRegistry.create`'s "a flag for a non-enum engine cannot be
created at all, on or off" guarantee at the values-file layer.
"""

from __future__ import annotations

from typing import Any

from saena_schemas.common.engine_id_v1 import EngineId

from saena_forgectl.checks._util import get_path
from saena_forgectl.models import CheckResult

CHECK_NAME = "engine_flags"

#: The v1 closed enum, read from the same generated artifact
#: `saena_engine_gateway.registry.PERMITTED_ENGINE_IDS` consults.
PERMITTED_ENGINE_IDS: frozenset[str] = frozenset(item.value for item in EngineId)

#: Every `global.engineScope` key this check recognizes, mapped to the
#: canonical `engine_id` it represents. A key mapping to a value *outside*
#: `PERMITTED_ENGINE_IDS` is a named, well-known non-v1 engine (kept in this
#: map so its failure message is specific — "googleAiOverviews (engine_id
#: 'google-ai-overviews') is enabled" — rather than merely "unrecognized
#: key").
_KNOWN_FLAG_KEYS: dict[str, str] = {
    "chatgptSearch": "chatgpt-search",
    "googleAiOverviews": "google-ai-overviews",
    "googleAiMode": "google-ai-mode",
    "gemini": "gemini",
    "google": "google",
    "bard": "bard",
}


def check_engine_flags(values: dict[str, Any]) -> CheckResult:
    """Fail iff any enabled `global.engineScope` entry resolves to an
    `engine_id` outside the v1 closed enum — named or unrecognized.

    Also fails (separately reported in `context`) on any `engineScope` key
    that is not in `_KNOWN_FLAG_KEYS` at all, even if that key's value is
    `false` — an unrecognized key is itself evidence of a rogue/near-miss
    engine declaration slipping past whatever produced this values file,
    and this check does not try to guess whether it was meant to be
    harmless.
    """
    engine_scope = get_path(values, "global", "engineScope")
    if engine_scope is None:
        return CheckResult(
            name=CHECK_NAME,
            passed=False,
            detail="global.engineScope is not declared — engine scope must be explicit",
            context={},
        )
    if not isinstance(engine_scope, dict):
        return CheckResult(
            name=CHECK_NAME,
            passed=False,
            detail=(
                "global.engineScope must be a mapping of flag name to boolean, "
                f"got {type(engine_scope).__name__}"
            ),
            context={},
        )

    disallowed_enabled: dict[str, str] = {}
    unrecognized_keys: list[str] = []

    for flag_key, flag_value in engine_scope.items():
        engine_id = _KNOWN_FLAG_KEYS.get(flag_key)
        if engine_id is None:
            unrecognized_keys.append(flag_key)
            continue
        if engine_id not in PERMITTED_ENGINE_IDS and bool(flag_value):
            disallowed_enabled[flag_key] = engine_id

    if not disallowed_enabled and not unrecognized_keys:
        chatgpt_enabled = bool(engine_scope.get("chatgptSearch", False))
        return CheckResult(
            name=CHECK_NAME,
            passed=True,
            detail="engine flags are within the v1 closed enum (chatgpt-search only)",
            context={"chatgptSearch_enabled": chatgpt_enabled},
        )

    detail_parts: list[str] = []
    if disallowed_enabled:
        named = ", ".join(
            f"{flag_key} (engine_id {engine_id!r})"
            for flag_key, engine_id in sorted(disallowed_enabled.items())
        )
        detail_parts.append(f"non-v1 engine flag(s) enabled: {named}")
    if unrecognized_keys:
        detail_parts.append(
            "unrecognized engineScope key(s): " + ", ".join(sorted(unrecognized_keys))
        )

    return CheckResult(
        name=CHECK_NAME,
        passed=False,
        detail=(
            "; ".join(detail_parts)
            + " — v1 closed enum is {'chatgpt-search'} only (CLAUDE.md Engine scope v1)"
        ),
        context={
            "disallowed_enabled": disallowed_enabled,
            "unrecognized_keys": sorted(unrecognized_keys),
        },
    )
