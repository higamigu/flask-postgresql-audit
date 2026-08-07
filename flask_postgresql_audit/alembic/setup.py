import logging
from typing import TYPE_CHECKING

from alembic.autogenerate import comparators
from alembic.autogenerate.api import AutogenContext
from alembic.operations import ops
from alembic.operations.ops import MigrationScript
from alembic.util import DispatchPriority
from alembic_utils.replaceable_entity import register_entities, registry
from alembic_utils.reversible_op import CreateOp
from sqlalchemy import Connection, text
from sqlalchemy.orm import Session

from . import entities
from .schema import SchemaCreate

if TYPE_CHECKING:
    from alembic_utils.replaceable_entity import ReplaceableEntity

    from ..core import PostgreSQLAudit


logger = logging.getLogger("pg_audit.setup")


def setup_db(audit: "PostgreSQLAudit"):
    register_core_entities(audit)
    register_triggers(audit)
    register_entities(audit.pg_audit_entities)

    @comparators.dispatch_for("schema", priority=DispatchPriority.FIRST)
    def compare_audit_schema(
        autogen_context: AutogenContext,
        upgrade_ops: ops.UpgradeOps,
        schemas: set[None] | set[str | None],
    ) -> None:
        if connection := autogen_context.connection:
            check_schema = """
                SELECT TRUE FROM information_schema.schemata
                WHERE schema_name = '{name}'
            """.format(name=audit.context["schema_name"])
            if not connection.scalar(text(check_schema)):
                upgrade_ops.ops.append(SchemaCreate(audit.context["schema_name"]))

            for ent in audit.pg_audit_entities:
                if op := get_blind_migration_op(ent, connection):
                    registry._entities.pop(ent.identity, None)
                    upgrade_ops.ops.append(op)


def reorder_migration_ops(context, revision, directives: list[MigrationScript]):
    """
    Alembic directive listener that reorders upgrade operations into correct
    dependency order:
    1. Schema creation & btree_gist extension
    2. Tables, indexes, foreign keys, etc.
    3. Triggers & Replaceable audit entities
    """
    for directive in directives:
        if not hasattr(directive, "upgrade_ops") or directive.upgrade_ops is None:
            continue

        upgrade_ops = directive.upgrade_ops.ops

        schema_ops = []
        extension_ops = []
        trigger_ops = []
        other_ops = []

        for op in upgrade_ops:
            if isinstance(op, SchemaCreate):
                schema_ops.append(op)
            elif (
                isinstance(op, CreateOp)
                and getattr(op.target, "signature", None) == "btree_gist"
            ):
                extension_ops.append(op)
            elif isinstance(op, CreateOp):
                trigger_ops.append(op)
            else:
                other_ops.append(op)

        # Reassemble the ops sequence in strict dependency order
        directive.upgrade_ops.ops = schema_ops + extension_ops + other_ops + trigger_ops


def chain_revision_directives(*callbacks):
    """
    Chain multiple process_revision_directives callbacks together into a single
    listener for Alembic's context.configure().
    """

    def wrapper(context, revision, directives: list[MigrationScript]):
        for cb in callbacks:
            cb(context, revision, directives)

    return wrapper


def register_core_entities(audit: "PostgreSQLAudit"):
    audit.pg_audit_entities.add(entities.btree_gist)
    audit.pg_audit_entities.add(entities.get_pk_values(**audit.context))
    audit.pg_audit_entities.add(entities.get_table_relid(**audit.context))
    audit.pg_audit_entities.add(entities.get_setting_factory(**audit.context))
    audit.pg_audit_entities.add(entities.jsonb_subtract_factory(**audit.context))
    audit.pg_audit_entities.add(entities.create_activity_factory(**audit.context))


def register_triggers(audit: "PostgreSQLAudit"):
    for cls in audit.pg_audit_classes:
        exclude = cls.__audit_args__.get("exclude", [])
        ctx = dict(
            table_name=cls.__tablename__,
            table_schema=cls.__table__.schema or "public",
            excluded_columns="'{" + ",".join(exclude) + "}'",
            **audit.context,
        )

        audit.pg_audit_entities.add(entities.trigger_insert_factory(**ctx))
        audit.pg_audit_entities.add(entities.trigger_update_factory(**ctx))
        audit.pg_audit_entities.add(entities.trigger_delete_factory(**ctx))


def get_blind_migration_op(entity: "ReplaceableEntity", connection: Connection):
    session = Session(bind=connection)
    db_ents: list[ReplaceableEntity] = entity.from_database(session, entity.schema)

    for db_ent in db_ents:
        if entity.identity == db_ent.identity:
            return None  # Offload migration op creation to alembic_utils if exist
    logger.info("Detected blind CreateOp %s", entity.identity)
    return CreateOp(entity)
