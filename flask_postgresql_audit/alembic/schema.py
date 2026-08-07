from alembic.autogenerate import renderers
from alembic.autogenerate.api import AutogenContext
from alembic.operations import MigrateOperation, Operations
from sqlalchemy import text

# Operations #


class SchemaOperation(MigrateOperation):
    def __init__(self, schema_name) -> None:
        self.schema_name = schema_name

    @classmethod
    def invoke_for_schema(cls, operations: Operations, schema_name: str):
        return operations.invoke(cls(schema_name))


@Operations.register_operation("create_schema", "invoke_for_schema")
class SchemaCreate(SchemaOperation):
    def reverse(self) -> MigrateOperation:
        return SchemaDrop(self.schema_name)


@Operations.register_operation("drop_schema", "invoke_for_schema")
class SchemaDrop(SchemaOperation):
    def reverse(self) -> MigrateOperation:
        return SchemaCreate(self.schema_name)


# Implementations #


@Operations.implementation_for(SchemaCreate)
def create_schema(operations: Operations, operation: SchemaCreate):
    stmt = f"""
        CREATE SCHEMA {operation.schema_name};
        REVOKE ALL ON SCHEMA {operation.schema_name} FROM public;
    """
    operations.execute(text(stmt))


@Operations.implementation_for(SchemaDrop)
def drop_schema(operations: Operations, operation: SchemaDrop):
    stmt = f"DROP SCHEMA {operation.schema_name} CASCADE;"
    operations.execute(text(stmt))


# Render #


@renderers.dispatch_for(SchemaCreate)
def render_create_schema(autogen_context: AutogenContext, op: SchemaCreate) -> str:
    return f'op.create_schema("{op.schema_name}")'


@renderers.dispatch_for(SchemaDrop)
def render_drop_schema(autogen_context: AutogenContext, op: SchemaDrop) -> str:
    return f'op.drop_schema("{op.schema_name}")'
