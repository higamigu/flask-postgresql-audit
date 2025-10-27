from typing import TYPE_CHECKING, Optional, Set, Union

from alembic.autogenerate import comparators, renderers
from alembic.autogenerate.api import AutogenContext
from alembic.operations import MigrateOperation, Operations, ops
from alembic_utils.replaceable_entity import register_entities
from sqlalchemy import text

from flask_postgresql_audit.utils import load_template

from . import entities

if TYPE_CHECKING:
    from alembic_utils.replaceable_entity import ReplaceableEntity

    from ..core import Audit


def register_triggers(audit_classes: "set[type[Audit]]", **context):
    triggers: "set[ReplaceableEntity]" = set()
    for cls in audit_classes:
        exclude = cls.__audit_args__.get("exclude", [])

        ctx = dict(table_name=cls.__tablename__, **context)
        ctx["excluded_columns"] = "'{" + ",".join(exclude) + "}'"

        triggers.add(entities.trigger_insert_factory(**ctx))
        triggers.add(entities.trigger_update_factory(**ctx))
        triggers.add(entities.trigger_delete_factory(**ctx))

    register_entities(triggers)


def setup_schema(**context):
    core_ents = [
        entities.btree_gist,
        entities.get_setting_factory(**context),
        entities.jsonb_subtract_factory(**context),
    ]

    @Operations.register_operation("pg_audit_schema_init")
    class PGAuditSchemaInitOp(MigrateOperation):
        @classmethod
        def pg_audit_schema_init(cls, operations: Operations):
            op = PGAuditSchemaInitOp()
            return operations.invoke(op)

        def reverse(self):
            return PGAuditSchemaRemoveOp()

    @Operations.register_operation("pg_audit_schema_remove")
    class PGAuditSchemaRemoveOp(MigrateOperation):
        @classmethod
        def pg_audit_schema_remove(cls, operations: Operations):
            op = PGAuditSchemaRemoveOp()
            return operations.invoke(op)

        def reverse(self):
            return PGAuditSchemaInitOp()

    @Operations.implementation_for(PGAuditSchemaInitOp)
    def _impl_init(operations: Operations, operation: PGAuditSchemaInitOp):
        stmt = load_template("create_schema.sql").substitute(**context)
        operations.execute(text(stmt))

    @Operations.implementation_for(PGAuditSchemaRemoveOp)
    def _impl_remove(operations: Operations, operation: PGAuditSchemaRemoveOp):
        stmt = load_template("drop_schema.sql").substitute(**context)
        operations.execute(text(stmt))

    @renderers.dispatch_for(PGAuditSchemaInitOp)
    def _render_init(autogen_context: AutogenContext, op: ops.ExecuteSQLOp) -> str:
        return "op.pg_audit_schema_init()"

    @renderers.dispatch_for(PGAuditSchemaRemoveOp)
    def _render_remove(autogen_context: AutogenContext, op: ops.ExecuteSQLOp) -> str:
        return "op.pg_audit_schema_remove()"

    @comparators.dispatch_for("schema")
    def _compare(
        autogen_context: AutogenContext,
        upgrade_ops: ops.UpgradeOps,
        schemas: Union[Set[None], Set[Optional[str]]],
    ) -> None:
        if connection := autogen_context.connection:
            check_stmt = """
                SELECT TRUE FROM information_schema.schemata
                WHERE schema_name = '{schema_name}'
            """.format(**context)
            if not connection.scalar(text(check_stmt)):
                upgrade_ops.ops.insert(0, PGAuditSchemaInitOp())

    register_entities(core_ents)
