import pytest
from alembic_utils.exceptions import SQLParseFailure
from sqlalchemy import text

from flask_postgresql_audit.extensions.alembic_utils import PGAggregate
from tests.app import audit, db


@pytest.mark.usefixtures("test_client")
class TestPGAggregate:
    def test_properties_and_signatures(self):
        agg = PGAggregate(
            schema="public",
            signature="custom_sum(numeric)",
            definition="(SFUNC = numeric_add, STYPE = numeric, INITCOND = '0')",
        )
        assert agg.type_ == "aggregate"
        assert agg.literal_signature == '"custom_sum"(numeric)'

    def test_from_sql_parsing(self):
        sql = "CREATE AGGREGATE public.custom_sum(numeric) (SFUNC = numeric_add, STYPE = numeric, INITCOND = '0')"
        agg = PGAggregate.from_sql(sql)

        assert agg.schema == "public"
        assert agg.signature == "custom_sum(numeric)"
        assert (
            agg.definition == "(SFUNC = numeric_add, STYPE = numeric, INITCOND = '0')"
        )

        # Quoted signature in SQL
        sql_quoted = 'CREATE AGGREGATE public."custom_sum"(numeric) (SFUNC = numeric_add, STYPE = numeric)'
        agg_quoted = PGAggregate.from_sql(sql_quoted)
        assert agg_quoted.signature == "custom_sum(numeric)"

        # Invalid SQL raises SQLParseFailure
        with pytest.raises(SQLParseFailure):
            PGAggregate.from_sql("INVALID SQL STATEMENT")

    def test_sql_statement_generation(self):
        agg = PGAggregate(
            schema="public",
            signature="custom_sum(numeric)",
            definition="(SFUNC = numeric_add, STYPE = numeric)",
        )

        create_sql = str(agg.to_sql_statement_create())
        assert (
            create_sql
            == 'CREATE AGGREGATE "public"."custom_sum"(numeric) (SFUNC = numeric_add, STYPE = numeric)'
        )

        create_or_replace = list(agg.to_sql_statement_create_or_replace())
        assert len(create_or_replace) == 1
        assert (
            str(create_or_replace[0])
            == 'CREATE OR REPLACE AGGREGATE "public"."custom_sum"(numeric) (SFUNC = numeric_add, STYPE = numeric)'
        )

        drop_sql = str(agg.to_sql_statement_drop())
        assert drop_sql == 'DROP AGGREGATE "public"."custom_sum"(numeric)'

        drop_cascade_sql = str(agg.to_sql_statement_drop(cascade=True))
        assert (
            drop_cascade_sql == 'DROP AGGREGATE "public"."custom_sum"(numeric) CASCADE'
        )

    def test_from_database(self):
        schema = audit.context["schema_name"]
        prefix = audit.context["schema_prefix"]

        # Create temporary custom aggregate in DB
        db.session.execute(
            text(
                f"""
                CREATE OR REPLACE AGGREGATE {prefix}test_sum(numeric) (
                    SFUNC = numeric_add,
                    STYPE = numeric,
                    INITCOND = '0'
                );
                """
            )
        )
        db.session.commit()

        try:
            aggregates = PGAggregate.from_database(db.session, schema=schema)  # type: ignore
            matching = [
                a for a in aggregates if a.identity.endswith("test_sum(numeric)")
            ]
            assert len(matching) == 1
            assert matching[0].schema == schema
        finally:
            db.session.execute(
                text(f"DROP AGGREGATE IF EXISTS {prefix}test_sum(numeric);")
            )
            db.session.commit()
