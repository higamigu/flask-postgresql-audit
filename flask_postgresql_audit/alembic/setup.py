import logging
from typing import TYPE_CHECKING, Optional, Set, Union

from alembic.autogenerate import comparators
from alembic.autogenerate.api import AutogenContext
from alembic.operations import ops
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

    def compare_audit_schema(
        autogen_context: AutogenContext,
        upgrade_ops: ops.UpgradeOps,
        schemas: Union[Set[None], Set[Optional[str]]],
    ) -> None:
        if connection := autogen_context.connection:
            check_schema = """
                SELECT TRUE FROM information_schema.schemata
                WHERE schema_name = '{name}'
            """.format(name=audit.context["schema_name"])
            if not connection.scalar(text(check_schema)):
                upgrade_ops.ops.insert(0, SchemaCreate(audit.context["schema_name"]))

            for ent in audit.pg_audit_entities:
                if op := get_blind_migration_op(ent, connection):
                    registry._entities.pop(ent.identity)
                    upgrade_ops.ops.append(op)

    for idx, comp_fn in enumerate(comparators._registry.get(("schema", "default"), [])):
        # Insert pg_audit comparators before alembic_utils comparators
        # to override alembic_utils migration caveats when entity
        # depend on new object in same migration
        if comp_fn.__module__ == "alembic_utils.replaceable_entity":
            comparators._registry.setdefault(("schema", "default"), []).insert(
                idx, compare_audit_schema
            )
            break


def register_core_entities(audit: "PostgreSQLAudit"):
    audit.pg_audit_entities.add(entities.btree_gist)
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
    db_ents: list["ReplaceableEntity"] = entity.from_database(session, entity.schema)

    for db_ent in db_ents:
        if entity.identity == db_ent.identity:
            return None  # Offload migration op creation to alembic_utils if exist
    logger.info("Detected blind CreateOp %s", entity.identity)
    return CreateOp(entity)
