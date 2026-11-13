from __future__ import annotations

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
from .utils import downgrade, revision, upgrade


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


@pytest.mark.usefixtures("test_client")
class TestXID8LegacyMigrationGeneration:
    """Autogenerate must produce a runnable migration for a 1.0.x database."""

    def _revert_to_legacy_layout(self):
        schema = audit.schema_name or "public"
        prefix = "" if schema == "public" else f"{schema}."

        statements = [
            "CREATE EXTENSION IF NOT EXISTS btree_gist",
            (
                f"ALTER TABLE {prefix}pga_transaction"
                " DROP CONSTRAINT pga_transaction_unique_native_tx_id"
            ),
            (
                f"ALTER TABLE {prefix}pga_transaction"
                " ALTER COLUMN native_transaction_id TYPE bigint"
                " USING native_transaction_id::text::bigint"
            ),
            (
                f"ALTER TABLE {prefix}pga_activity"
                " ALTER COLUMN native_transaction_id TYPE bigint"
                " USING native_transaction_id::text::bigint"
            ),
            (
                f"ALTER TABLE {prefix}pga_transaction"
                " ADD CONSTRAINT pga_transaction_unique_native_tx_id"
                " EXCLUDE USING gist ("
                " native_transaction_id WITH =,"
                " tsrange(issued_at - INTERVAL '1 hour', issued_at) WITH &&)"
            ),
        ]

        with db.engine.begin() as connection:
            for statement in statements:
                connection.execute(sa.text(statement))

    def _native_transaction_columns(self):
        inspector = sa.inspect(db.engine)
        schema = audit.schema_name or None

        return {
            table_name: {
                column["name"]: column["type"]
                for column in inspector.get_columns(table_name, schema=schema)
            }["native_transaction_id"]
            for table_name in ("pga_activity", "pga_transaction")
        }

    def _native_transaction_constraint(self):
        schema = audit.schema_name or "public"
        query = sa.text(
            """
            SELECT c.contype
            FROM pg_constraint AS c
            JOIN pg_class AS t ON t.oid = c.conrelid
            JOIN pg_namespace AS n ON n.oid = t.relnamespace
            WHERE t.relname = 'pga_transaction'
              AND n.nspname = :schema
              AND c.conname = 'pga_transaction_unique_native_tx_id'
            """
        )
        with db.engine.connect() as connection:
            return connection.scalar(query, {"schema": schema})

    def test_autogenerated_migration_swaps_legacy_constraint(self, alembic_config_path):
        self._revert_to_legacy_layout()

        revision(
            db.engine,
            alembic_config_path,
            autogenerate=True,
            rev_id="2",
            message="xid8",
        )

        generated = next((alembic_config_path / "versions").glob("2_*.py")).read_text()

        drop_constraint = (
            "ALTER TABLE public.pga_transaction"
            " DROP CONSTRAINT pga_transaction_unique_native_tx_id"
        )
        if audit.schema_name:
            drop_constraint = drop_constraint.replace(
                "public.", f"{audit.schema_name}."
            )

        assert drop_constraint in generated
        assert (
            generated.count("postgresql_using='native_transaction_id::text::xid8'") == 2
        )
        assert generated.index(drop_constraint) < generated.index(
            "create_unique_constraint('pga_transaction_unique_native_tx_id'"
        )

        upgrade(db.engine, alembic_config_path, revision="head")

        assert all(
            isinstance(type_, XID8)
            for type_ in self._native_transaction_columns().values()
        )
        assert self._native_transaction_constraint() == "u"

        downgrade(db.engine, alembic_config_path, revision="1")

        assert all(
            isinstance(type_, sa.BigInteger)
            for type_ in self._native_transaction_columns().values()
        )
        assert self._native_transaction_constraint() == "x"

        # Leave the database consistent with the model metadata again.
        upgrade(db.engine, alembic_config_path, revision="head")

        assert all(
            isinstance(type_, XID8)
            for type_ in self._native_transaction_columns().values()
        )
        assert self._native_transaction_constraint() == "u"
