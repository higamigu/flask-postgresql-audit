from typing import Any

import sqlalchemy as sa
from alembic.autogenerate import render, renderers
from alembic.autogenerate.api import AutogenContext
from alembic.operations import ops
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql.base import PGDialect

from ..types import XID8


class XID8AlterColumnOp(ops.AlterColumnOp):
    """Alter column operation that renders a PostgreSQL ``USING`` clause."""

    def __init__(self, *args: Any, postgresql_using: str, **kw: Any) -> None:
        super().__init__(*args, **kw)
        self.postgresql_using = postgresql_using


@renderers.dispatch_for(XID8AlterColumnOp)
def render_xid8_alter_column(
    autogen_context: AutogenContext, op: XID8AlterColumnOp
) -> str:
    text = render._alter_column(autogen_context, op)
    return text[:-1] + f",\n           postgresql_using={op.postgresql_using!r})"


def register_xid8_type() -> None:
    """Register ``xid8`` with SQLAlchemy reflection and Alembic rendering."""
    # Expose the type through the PostgreSQL dialect so Alembic renders it as
    # ``postgresql.XID8()`` and imports the dialect in generated migrations.
    XID8.__module__ = postgresql.__name__
    if not hasattr(postgresql, "XID8"):
        postgresql.XID8 = XID8  # ty: ignore[missing-attribute]

    # Let SQLAlchemy reflect existing ``xid8`` columns with this type.
    PGDialect.ischema_names.setdefault("xid8", XID8)  # ty: ignore[no-matching-overload]


def _xid8_using_clause(op: ops.AlterColumnOp) -> str | None:
    if op.column_name != "native_transaction_id":
        return None

    existing = op.existing_type
    modify = op.modify_type

    if isinstance(modify, XID8) and isinstance(existing, sa.BigInteger):
        return f"{op.column_name}::text::xid8"
    if isinstance(existing, XID8) and isinstance(modify, sa.BigInteger):
        return f"{op.column_name}::text::bigint"
    return None


def _make_xid8_alter_column_op(op: ops.AlterColumnOp, using: str) -> XID8AlterColumnOp:
    kw = dict(op.kw)
    kw.pop("postgresql_using", None)
    return XID8AlterColumnOp(
        op.table_name,
        op.column_name,
        schema=op.schema,
        existing_type=op.existing_type,
        existing_server_default=op.existing_server_default,
        existing_nullable=op.existing_nullable,
        existing_comment=op.existing_comment,
        modify_nullable=op.modify_nullable,
        modify_comment=op.modify_comment,
        modify_server_default=op.modify_server_default,
        modify_name=op.modify_name,
        modify_type=op.modify_type,
        postgresql_using=using,
        **kw,
    )


def _replace_xid8_ops(container: ops.OpContainer) -> None:
    for index, op in enumerate(container.ops):
        if isinstance(op, XID8AlterColumnOp):
            continue
        if isinstance(op, ops.AlterColumnOp):
            if using := _xid8_using_clause(op):
                container.ops[index] = _make_xid8_alter_column_op(op, using)
        elif isinstance(op, ops.OpContainer):
            _replace_xid8_ops(op)


def apply_xid8_type_changes(directives: list[Any]) -> None:
    """Add ``USING`` clauses for ``native_transaction_id`` type migrations."""
    for directive in directives:
        for container in (
            getattr(directive, "upgrade_ops", None),
            getattr(directive, "downgrade_ops", None),
        ):
            if container is not None:
                _replace_xid8_ops(container)
