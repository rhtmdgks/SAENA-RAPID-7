"""`tests/unit/domain_execution` — makes this directory a package so its test
modules import as `domain_execution.test_*` (unique across the suite) rather
than bare `test_*` (which collides with same-named modules in sibling
test directories that also lack `__init__.py`, e.g. `test_errors.py` also
exists under `tests/unit/domain_identity`). Mirrors the
`tests/unit/domain_persistence` convention exactly (see that directory's
`conftest.py` docstring for the same rationale).
"""
