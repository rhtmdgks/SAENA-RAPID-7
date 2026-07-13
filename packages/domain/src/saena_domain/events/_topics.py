"""AsyncAPI-derived topic/producer catalog (ADR-0013 topic=event_type 1:1 rule).

Parses `packages/contracts/asyncapi/saena-events/v1/asyncapi.yaml` (read-only
consumption — this patch unit's exclusive write paths do NOT include
`packages/contracts/**`) to answer three questions without hardcoding the
catalog inline:

1. Is `event_type` a declared channel address? (`TopicMismatchError` if not)
2. Is `producer` the expected producer for that `event_type`? (derived from
   each `operations.*.summary` string, which follows the fixed convention
   `"<producer-service-id> produces <event_type>."` across all 12 CONFIRMED
   channels in the v1 catalog — see asyncapi.yaml `operations:` block)
3. Does this channel require `payload.engine_id` to be present (ADR-0013:
   "observation·citation·experiment 계열 이벤트 **payload**에 필수")? Parsed
   from each channel's `x-saena-engine-id-required: true` extension key —
   present on exactly 3 CONFIRMED v1 channels: `observation.captured.v1`,
   `citation.normalized.v1`, `experiment.outcome.observed.v1`.

Only the 6 channels that also declare a concrete `payload.$ref` under
`properties.payload` bind to a generated payload model
(`saena_schemas.event.*`); the other 6 are "envelope-only" channels per the
AsyncAPI file's own channel descriptions (payload contract not yet landed) —
`EVENT_PAYLOAD_MODELS` in `saena_domain.events.factory` is the source of
truth for which 6 those are, kept separate from this module so the
AsyncAPI-parsing concern and the payload-model-binding concern don't get
tangled.

Lazy + cached: the YAML file is parsed at most once per process (module-level
cache cleared only by `_reset_cache_for_tests()`, used by unit tests that
need to point at a fixture file).
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from pathlib import Path

import yaml

# saena_domain/events/_topics.py -> saena_domain/events -> saena_domain -> src
# -> packages/domain -> packages -> <repo root>
_REPO_ROOT = Path(__file__).resolve().parents[5]
_ASYNCAPI_PATH = (
    _REPO_ROOT / "packages" / "contracts" / "asyncapi" / "saena-events" / "v1" / "asyncapi.yaml"
)

_PRODUCES_PATTERN = re.compile(r"^(?P<producer>\S+)\s+produces\s+(?P<event_type>\S+)\.$")


@dataclass(frozen=True)
class TopicInfo:
    """One AsyncAPI channel: its address (== `event_type`), producer, and
    whether `payload.engine_id` is required (channel `x-saena-engine-id-required`).
    """

    event_type: str
    expected_producer: str
    engine_id_required: bool = False


class TopicCatalogError(RuntimeError):
    """The AsyncAPI file could not be parsed into a usable topic catalog."""


_lock = threading.Lock()
_cache: dict[str, TopicInfo] | None = None
_cache_path: Path | None = None


def _parse(asyncapi_path: Path) -> dict[str, TopicInfo]:
    document = yaml.safe_load(asyncapi_path.read_text(encoding="utf-8"))
    channels = document.get("channels", {})
    operations = document.get("operations", {})

    catalog: dict[str, TopicInfo] = {}
    for address, channel in channels.items():
        engine_id_required = bool(channel.get("x-saena-engine-id-required", False))
        catalog[address] = TopicInfo(
            event_type=address,
            expected_producer="",
            engine_id_required=engine_id_required,
        )

    for op in operations.values():
        summary = op.get("summary", "")
        match = _PRODUCES_PATTERN.match(summary)
        if match is None:
            msg = (
                f"operation summary {summary!r} does not match the "
                "'<producer> produces <event_type>.' convention this catalog relies on"
            )
            raise TopicCatalogError(msg)
        event_type = match.group("event_type")
        producer = match.group("producer")
        existing = catalog.get(event_type)
        if existing is None:
            msg = f"operation summary references unknown channel address {event_type!r}"
            raise TopicCatalogError(msg)
        catalog[event_type] = TopicInfo(
            event_type=event_type,
            expected_producer=producer,
            engine_id_required=existing.engine_id_required,
        )

    missing_producer = [t for t, info in catalog.items() if not info.expected_producer]
    if missing_producer:
        msg = f"channels with no matching operation (no producer derivable): {missing_producer}"
        raise TopicCatalogError(msg)

    return catalog


def load_topic_catalog(asyncapi_path: Path = _ASYNCAPI_PATH) -> dict[str, TopicInfo]:
    """Return `{event_type: TopicInfo}` for every channel declared in the
    AsyncAPI catalog, parsing + caching on first call (per `asyncapi_path`).
    """
    global _cache, _cache_path
    with _lock:
        if _cache is not None and _cache_path == asyncapi_path:
            return _cache
        _cache = _parse(asyncapi_path)
        _cache_path = asyncapi_path
        return _cache


def _reset_cache_for_tests() -> None:
    """Clear the module-level cache. Test-only (unit tests point this
    module at a fixture AsyncAPI file and need a clean cache per case).
    """
    global _cache, _cache_path
    with _lock:
        _cache = None
        _cache_path = None
