"""Alembic support for the native transaction ID constraint swap.

Version ``1.1.x`` replaced the ``gist`` exclusion constraint on
``pga_transaction.native_transaction_id`` with a plain unique constraint.
Alembic never reflects exclusion constraints, so autogenerate cannot see the
legacy constraint and would emit ``create_unique_constraint`` while the old
constraint still owns the name, failing with a duplicate constraint error.

The operations below drop the legacy constraint before the ``bigint`` to
``xid8`` type change and restore it again on downgrade.
"""

from __future__ import annotations

import typing as t

from alembic.autogenerate import renderers
from alembic.operations import MigrateOperation
from sqlalchemy import Connection, text

if t.TYPE_CHECKING:
    from alembic.autogenerate.api import AutogenContext

CONSTRAINT_NAME = "pga_transaction_unique_native_tx_id"
TABLE_NAME = "pga_transaction"
EXCLUSION_ELEMENTS = (
    "native_transaction_id WITH =",
    "tsrange(issued_at - INTERVAL '1 hour', issued_at) WITH &&",
)


class NativeTransactionConstraintOp(MigrateOperation):
    """Drop or create the legacy native transaction ID exclusion constraint."""

    def __init__(self, *, drop_sql: str, create_sql: str, drop: bool = True) -> None:
        self.drop_sql = drop_sql
        self.create_sql = create_sql
        self.drop = drop

    @property
    def sqltext(self) -> str:
        return self.drop_sql if self.drop else self.create_sql

    def reverse(self) -> NativeTransactionConstraintOp:
        return NativeTransactionConstraintOp(
            drop_sql=self.drop_sql,
            create_sql=self.create_sql,
            drop=not self.drop,
        )

    def to_diff_tuple(self) -> tuple[t.Any, ...]:
        verb = (
            "drop_exclusion_constraint" if self.drop else "create_exclusion_constraint"
        )
        return (verb, TABLE_NAME, CONSTRAINT_NAME)

    def describe(self) -> str:  # pragma: no cover - debugging aid
        return self.sqltext


@renderers.dispatch_for(NativeTransactionConstraintOp)
def render_native_transaction_constraint(
    autogen_context: AutogenContext, op: NativeTransactionConstraintOp
) -> str:
    return f"op.execute({op.sqltext!r})"


def legacy_constraint_op(
    connection: Connection, schema_name: str | None
) -> NativeTransactionConstraintOp | None:
    """Return an operation dropping the legacy exclusion constraint if present."""
    schema = schema_name or "public"
    query = text(
        """
        SELECT c.contype
        FROM pg_constraint AS c
        JOIN pg_class AS t ON t.oid = c.conrelid
        JOIN pg_namespace AS n ON n.oid = t.relnamespace
        WHERE t.relname = :table
          AND n.nspname = :schema
          AND c.conname = :constraint
        """
    )
    contype = connection.scalar(
        query,
        {
            "table": TABLE_NAME,
            "schema": schema,
            "constraint": CONSTRAINT_NAME,
        },
    )
    if contype != "x":
        return None

    preparer = connection.dialect.identifier_preparer
    table = f"{preparer.quote_schema(schema)}.{preparer.quote(TABLE_NAME)}"
    constraint = preparer.quote(CONSTRAINT_NAME)

    return NativeTransactionConstraintOp(
        drop_sql=f"ALTER TABLE {table} DROP CONSTRAINT {constraint}",
        create_sql=(
            f"ALTER TABLE {table} ADD CONSTRAINT {constraint}"
            f" EXCLUDE USING gist ({', '.join(EXCLUSION_ELEMENTS)})"
        ),
    )
