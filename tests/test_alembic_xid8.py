from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata, render
from alembic.autogenerate.api import AutogenContext
from alembic.migration import MigrationContext
from alembic.operations import ops

from flask_postgresql_audit.alembic import apply_xid8_type_changes
from flask_postgresql_audit.alembic.xid8 import XID8AlterColumnOp
from flask_postgresql_audit.types import XID8

from .app import audit, db


@pytest.mark.usefixtures("test_client")
class TestXID8AlembicSupport:
    def test_columns_reflect_as_xid8(self):
        inspector = sa.inspect(db.engine)

        schema = audit.schema_name or None
        for table_name in ("pga_activity", "pga_transaction"):
            columns = {
                column["name"]: column["type"]
                for column in inspector.get_columns(table_name, schema=schema)
            }
            assert isinstance(columns["native_transaction_id"], XID8)

    def test_autogenerate_does_not_change_xid8_columns(self):
        with db.engine.connect() as connection:
            context = MigrationContext.configure(
                connection, opts={"include_schemas": True}
            )
            diffs = compare_metadata(context, db.metadata)

        assert not any(
            isinstance(diff, tuple)
            and diff[0] == "modify_type"
            and diff[3] == "native_transaction_id"
            for diff in diffs
        )

    def test_adds_using_clause_when_upgrading_to_xid8(self):
        alter = ops.AlterColumnOp(
            "pga_activity",
            "native_transaction_id",
            existing_type=sa.BigInteger(),
            modify_type=XID8(),
        )
        directive = SimpleNamespace(
            upgrade_ops=ops.UpgradeOps(ops=[alter]),
            downgrade_ops=None,
        )

        apply_xid8_type_changes([directive])

        result = directive.upgrade_ops.ops[0]
        assert isinstance(result, XID8AlterColumnOp)
        assert result.postgresql_using == "native_transaction_id::text::xid8"

    def test_adds_using_clause_when_downgrading_to_bigint(self):
        alter = ops.AlterColumnOp(
            "pga_activity",
            "native_transaction_id",
            existing_type=XID8(),
            modify_type=sa.BigInteger(),
        )
        directive = SimpleNamespace(
            upgrade_ops=ops.UpgradeOps(ops=[]),
            downgrade_ops=ops.DowngradeOps(ops=[alter]),
        )

        apply_xid8_type_changes([directive])

        result = directive.downgrade_ops.ops[0]
        assert isinstance(result, XID8AlterColumnOp)
        assert result.postgresql_using == "native_transaction_id::text::bigint"

    def test_renders_using_clause(self):
        alter = XID8AlterColumnOp(
            "pga_activity",
            "native_transaction_id",
            existing_type=sa.BigInteger(),
            modify_type=XID8(),
            postgresql_using="native_transaction_id::text::xid8",
        )
        context = AutogenContext(
            MigrationContext.configure(dialect_name="postgresql"),
            opts={
                "alembic_module_prefix": "op.",
                "sqlalchemy_module_prefix": "sa.",
                "user_module_prefix": None,
                "include_schemas": True,
            },
        )

        rendered = render.render_op_text(context, alter)

        assert "postgresql_using='native_transaction_id::text::xid8'" in rendered
