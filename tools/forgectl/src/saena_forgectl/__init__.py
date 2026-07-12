"""`saena_forgectl` — SAENA FORGE k3s package operator CLI (w2-19, W2C).

`forgectl preflight` is the k3s Package and Operations Spec §8.1 static
config gate: it validates a declarative Helm values YAML against the six
fail conditions the spec names, before any `helm upgrade --install
saena-forge …` is attempted. See `tools/forgectl/README.md` for scope,
packaging notes, and the documented live-cluster extension point.
"""

from __future__ import annotations

__version__ = "0.1.0"
