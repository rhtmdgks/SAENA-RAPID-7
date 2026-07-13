"""Tenant-scoped query + insert builder (w4-06 mission deliverable 2).

Spec basis: `docs/architecture/tenancy-model.md`/`security-model.md`
("cross-tenant query blocked at adapter API" — mission instruction verbatim),
ADR-0007 rev.2 §5 (`ORDER BY (tenant_id, ...)` prefix — every table's own
physical layout already favors a `tenant_id`-first predicate).

STRUCTURAL tenant injection is the entire point of this module: there is no
code path here capable of producing a runnable SELECT without a `tenant_id`
predicate baked into it. The only way to obtain a `TenantScopedQuery` is
`AnalyticsQuery.for_tenant(table, tenant_id)`, which takes `tenant_id` as a
required (non-defaulted) positional argument and writes it into the query's
`where_sql`/`params` at construction time — there is no
`TenantScopedQuery.__init__` a caller can invoke directly with a different
shape (the class is frozen and every field is populated by `for_tenant`), no
keyword to opt out of the tenant predicate, and no method on
`TenantScopedQuery` that removes or overrides the `tenant_id` clause once
set — `.filter_eq`/`.with_time_range`/`.with_limit` all return a NEW
`TenantScopedQuery` built via `dataclasses.replace`, which by definition
carries the original `tenant_id`/`where_sql` prefix forward unchanged. A
caller who wants an "all tenants" query is not offered that operation at
all — this module deliberately never grows one.

`build_insert_columns` similarly refuses to build an INSERT for any mapping
that lacks a non-empty `tenant_id` key, independent of `TenantScopedQuery`
(rows are inserted, never selected, through this second function) —
`store.py`'s `_append` calls it directly.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from saena_analytics_clickhouse.errors import TenantIsolationError
from saena_analytics_clickhouse.identifiers import validate_tenant_id
from saena_analytics_clickhouse.schema import require_known_table


@dataclass(frozen=True, slots=True)
class TenantScopedQuery:
    """An immutable, always-tenant-scoped SELECT builder.

    Construct ONLY via `AnalyticsQuery.for_tenant` — see module docstring.
    """

    table: str
    tenant_id: str
    where_sql: tuple[str, ...]
    params: dict[str, Any]
    order_by: str = "occurred_at"
    limit: int | None = None

    def filter_eq(self, column: str, value: Any) -> TenantScopedQuery:
        """Return a NEW query with an additional `column = %(...)s` clause
        (the `tenant_id` clause set by `for_tenant` is always still first —
        this only APPENDS)."""
        param_name = f"eq_{column}_{len(self.where_sql)}"
        return replace(
            self,
            where_sql=(*self.where_sql, f"{column} = %({param_name})s"),
            params={**self.params, param_name: value},
        )

    def with_time_range(
        self, *, start: datetime | None = None, end: datetime | None = None
    ) -> TenantScopedQuery:
        """Return a NEW query additionally bounded to `occurred_at in
        [start, end)` (either bound may be omitted)."""
        where_sql = self.where_sql
        params = dict(self.params)
        if start is not None:
            where_sql = (*where_sql, "occurred_at >= %(range_start)s")
            params["range_start"] = start
        if end is not None:
            where_sql = (*where_sql, "occurred_at < %(range_end)s")
            params["range_end"] = end
        return replace(self, where_sql=where_sql, params=params)

    def with_limit(self, limit: int) -> TenantScopedQuery:
        if limit < 1:
            raise ValueError(f"limit must be >= 1, got {limit}")
        return replace(self, limit=limit)

    def to_select_sql(self, *, columns: tuple[str, ...] = ("*",)) -> tuple[str, dict[str, Any]]:
        """Render `(sql, params)` for a SELECT of `columns`.

        The `tenant_id` predicate (index 0 of `where_sql`, written by
        `AnalyticsQuery.for_tenant`) is ALWAYS present in the emitted SQL —
        it can never have been removed, only appended to, by construction
        (see class docstring).
        """
        column_sql = ", ".join(columns)
        where = " AND ".join(self.where_sql)
        sql = f"SELECT {column_sql} FROM {self.table} WHERE {where} ORDER BY {self.order_by}"
        if self.limit is not None:
            sql += f" LIMIT {int(self.limit)}"
        return sql, dict(self.params)


class AnalyticsQuery:
    """Entry point — the ONLY way to obtain a `TenantScopedQuery`."""

    @staticmethod
    def for_tenant(table: str, tenant_id: str) -> TenantScopedQuery:
        """Build a query scoped to `(table, tenant_id)` — `tenant_id` is a
        required positional argument; there is no default and no overload
        that omits it (mission: "structurally impossible to omit")."""
        require_known_table(table)
        validate_tenant_id(tenant_id)
        return TenantScopedQuery(
            table=table,
            tenant_id=tenant_id,
            where_sql=("tenant_id = %(tenant_id)s",),
            params={"tenant_id": tenant_id},
        )


def build_insert_columns(
    table: str, fields_map: dict[str, Any]
) -> tuple[tuple[str, ...], tuple[Any, ...]]:
    """Return `(columns, values)` for an INSERT of `fields_map` into `table`.

    Raises `TenantIsolationError` if `fields_map` lacks a non-empty
    `tenant_id` — this is the INSERT-side counterpart of
    `TenantScopedQuery`'s SELECT-side structural guarantee: `store.py`'s
    `_append` cannot construct an insert for a row whose `tenant_id` is
    missing (in practice unreachable anyway, since every `rows.py` model's
    `__post_init__` already requires a valid `tenant_id` — this is
    belt-and-suspenders defense-in-depth at the query-builder layer too).
    """
    require_known_table(table)
    tenant_id = fields_map.get("tenant_id")
    if not tenant_id:
        raise TenantIsolationError(
            "cannot build an INSERT without a non-empty tenant_id",
            context={"table": table},
        )
    columns = tuple(fields_map.keys())
    values = tuple(fields_map.values())
    return columns, values


__all__ = [
    "AnalyticsQuery",
    "TenantScopedQuery",
    "build_insert_columns",
]
