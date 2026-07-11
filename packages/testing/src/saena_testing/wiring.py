"""Workspace wiring probe used by the scaffold test suite."""

import saena_shared


def shared_version() -> str:
    return saena_shared.__version__
