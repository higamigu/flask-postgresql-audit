from alembic_utils.pg_extension import PGExtension
from alembic_utils.pg_function import PGFunction
from alembic_utils.pg_trigger import PGTrigger

from ..utils import parse_template

btree_gist = PGExtension(schema="public", signature="btree_gist")


def create_activity_factory(**context):
    sql = parse_template("create_activity.sql", **context)
    return PGFunction(
        schema=context["schema_name"],
        signature="create_activity()",
        definition=sql["definition"],
    )


def trigger_delete_factory(**context):
    sql = parse_template("audit_trigger_delete.sql", **context)
    return PGTrigger(
        schema=context["table_schema"],
        signature="audit_trigger_delete",
        on_entity=f"{context['table_schema']}.{context['table_name']}",
        definition=sql["definition"],
    )


def trigger_insert_factory(**context):
    sql = parse_template("audit_trigger_insert.sql", **context)
    return PGTrigger(
        schema=context["table_schema"],
        signature="audit_trigger_insert",
        on_entity=f"{context['table_schema']}.{context['table_name']}",
        definition=sql["definition"],
    )


def trigger_update_factory(**context):
    sql = parse_template("audit_trigger_update.sql", **context)
    return PGTrigger(
        schema=context["table_schema"],
        signature="audit_trigger_update",
        on_entity=f"{context['table_schema']}.{context['table_name']}",
        definition=sql["definition"],
    )


def get_pk_values(**context):
    sql = parse_template("get_pk_values.sql", **context)
    return PGFunction(
        schema=context["schema_name"],
        signature="get_pk_values(relid oid, row_data jsonb)",
        definition=sql["definition"],
    )


def get_setting_factory(**context):
    sql = parse_template("get_setting.sql", **context)
    return PGFunction(
        schema=context["schema_name"],
        signature="get_setting(setting text, fallback text)",
        definition=sql["definition"],
    )


def jsonb_subtract_factory(**context):
    context.setdefault("jsonb_subtract_join_type", "LEFT")
    sql = parse_template("jsonb_subtract.sql", **context)
    return PGFunction(
        schema=context["schema_name"],
        signature="jsonb_subtract(arg1 jsonb, arg2 jsonb)",
        definition=sql["definition"],
    )
