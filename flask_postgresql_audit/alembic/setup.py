import logging
from typing import TYPE_CHECKING, Optional, Set, Union

from alembic.autogenerate import comparators
from alembic.autogenerate.api import AutogenContext
from alembic.operations import ops
from alembic_utils.pg_trigger import PGTrigger
from alembic_utils.replaceable_entity import register_entities, registry
from alembic_utils.reversible_op import CreateOp
from sqlalchemy import Connection, text
from sqlalchemy.orm import Session

from . import entities
from .schema import SchemaCreate

if TYPE_CHECKING:
    from alembic.operations import MigrateOperation
    from alembic_utils.pg_extension import PGExtension
    from alembic_utils.pg_function import PGFunction
    from alembic_utils.replaceable_entity import ReplaceableEntity

    from ..core import PostgreSQLAudit


logger = logging.getLogger("pg_audit.setup")


def setup_db(audit: "PostgreSQLAudit"):
    register_core_entities(audit)
    register_triggers(audit)

    def compare_audit_schema(
        autogen_context: AutogenContext,
        upgrade_ops: ops.UpgradeOps,
        schemas: Union[Set[None], Set[Optional[str]]],
    ) -> None:
        if connection := autogen_context.connection:
            registered_entities = registry._entities.copy().items()
            deferred_entities: set[str] = set()
            deferred_signatures = list(get_create_table_signature(upgrade_ops.ops))

            check_schema = """
                SELECT TRUE FROM information_schema.schemata
                WHERE schema_name = '{name}'
            """.format(name=audit.context["schema_name"])
            if not connection.scalar(text(check_schema)):
                upgrade_ops.ops.insert(0, SchemaCreate(audit.context["schema_name"]))

                # Overrides alembic_utils entities that depend on new schema
                for ident, ent in registered_entities:
                    if ent.schema == audit.context["schema_name"]:
                        deferred_entities.add(ident)
                        deferred_signatures.extend(get_entity_signature(ent))

            # Overrides alembic_utils entities that depend on new object
            for ident, ent in registered_entities:
                if any(n in ent.definition for n in deferred_signatures):
                    deferred_entities.add(ident)
                    deferred_signatures.extend(get_entity_signature(ent))

            for ident in deferred_entities:
                ent = registry._entities.pop(ident)
                if op := get_blind_migration_op(ent, connection):
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
    core_ents: "list[PGExtension | PGFunction]" = [
        entities.btree_gist,
        entities.get_setting_factory(**audit.context),
        entities.jsonb_subtract_factory(**audit.context),
        entities.create_activity_factory(**audit.context),
    ]

    register_entities(core_ents)


def register_triggers(audit: "PostgreSQLAudit"):
    triggers: "set[PGTrigger]" = set()
    for cls in audit.pg_audit_classes:
        exclude = cls.__audit_args__.get("exclude", [])

        ctx = dict(table_name=cls.__tablename__, **audit.context)
        ctx["excluded_columns"] = "'{" + ",".join(exclude) + "}'"

        triggers.add(entities.trigger_insert_factory(**ctx))
        triggers.add(entities.trigger_update_factory(**ctx))
        triggers.add(entities.trigger_delete_factory(**ctx))

    register_entities(triggers)


def get_blind_migration_op(entity: "ReplaceableEntity", connection: Connection):
    session = Session(bind=connection)
    db_ents: list["ReplaceableEntity"] = entity.from_database(session, entity.schema)

    for db_ent in db_ents:
        if entity.identity == db_ent.identity:
            return None  # Offload migration op creation to alembic_utils if exist
    logger.info("Detected blind CreateOp %s", entity.identity)
    return CreateOp(entity)


def get_create_table_signature(upgrade_ops: "list[MigrateOperation]"):
    for op in upgrade_ops:
        if isinstance(op, ops.CreateTableOp):
            yield f"{op.schema or 'public'}.{op.table_name}"
            if op.schema == "public":
                yield op.table_name


def get_entity_signature(entity: "ReplaceableEntity"):
    signature = entity.signature.strip("()")
    yield f"{entity.schema}.{signature}"
    if entity.schema == "public":
        yield signature
