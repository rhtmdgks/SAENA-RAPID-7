"""Workspace wiring tests — written before the packages exist (TDD).

Proves: workspace members resolve, cross-member imports work in the
allowed direction (saena_testing -> saena_shared), and version metadata
is importable.
"""


def test_shared_importable() -> None:
    import saena_shared

    assert saena_shared.__version__


def test_testing_importable() -> None:
    import saena_testing

    assert saena_testing.__version__


def test_testing_may_depend_on_shared() -> None:
    from saena_testing import wiring

    assert wiring.shared_version() == __import__("saena_shared").__version__
