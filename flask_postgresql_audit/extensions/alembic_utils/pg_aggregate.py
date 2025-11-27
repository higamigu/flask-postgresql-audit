import re
import typing as t

import sqlalchemy as sa
from alembic_utils.exceptions import SQLParseFailure
from alembic_utils.replaceable_entity import ReplaceableEntity
from alembic_utils.statement import strip_terminating_semicolon
from sqlalchemy.orm import Session

T = t.TypeVar("T", bound="ReplaceableEntity")


class PGAggregate(ReplaceableEntity):
    def __init__(self, schema: str, signature: str, definition: str):
        super().__init__(schema, signature, definition)
        self.definition: str = strip_terminating_semicolon(definition)

    @property
    def type_(self):
        return "aggregate"

    @property
    def literal_signature(self):
        name, remainder = self.signature.split("(", 1)
        return '"' + name.strip() + '"(' + remainder

    @classmethod
    def from_sql(cls, sql: str) -> "PGAggregate":
        pattern = r"^CREATE\s+AGGREGATE\s+(?:(?P<schema>\w+)\.)?(?P<signature>.+)\s+(?P<definition>\(.*\))$"
        result = re.search(pattern, sql, re.IGNORECASE)
        if result is not None and isinstance(result, re.Match):
            raw_signature: str = result["signature"]
            signature = (
                "".join(raw_signature.split('"', 2))
                if raw_signature.startswith('"')
                else raw_signature
            )
            return cls(
                schema=result["schema"],
                signature=signature,
                definition=result["definition"],
            )
        raise SQLParseFailure(f'Failed to parse SQL into PGAggregate """{sql}"""')

    def to_sql_statement_create(self, *, replace: bool = False):
        return sa.text(
            f"{'CREATE OR REPLACE' if replace else 'CREATE'} AGGREGATE "
            f"{self.literal_schema}.{self.literal_signature} {self.definition}"
        )

    def to_sql_statement_create_or_replace(self):
        return self.to_sql_statement_create(replace=True)

    def to_sql_statement_drop(self, cascade=False):
        return sa.text(
            f"DROP AGGREGATE {self.literal_schema}.{self.literal_signature}"
            + (" CASCADE" if cascade else "")
        )

    @classmethod
    def from_database(cls, sess: Session, schema: str) -> "list[PGAggregate]":
        PG_GTE_11 = """
            and p.prokind = 'a'
        """

        # NOTE: not tested
        # PG_LT_11 = """
        #     and p.proisagg
        #     and not p.proiswindow
        # """

        # Retrieve the postgres server version e.g. 90603 for 9.6.3 or 120003 for 12.3
        pg_version_str = sess.execute(sa.text("show server_version_num")).scalar_one()
        pg_version = int(pg_version_str)

        sql = sa.text(
            """
            WITH extension_functions AS (
                SELECT objid AS extension_function_oid, classid
                FROM pg_depend
                WHERE deptype='e' -- depends on an extension
                    AND classid = 'pg_proc'::regclass -- is a proc/function
            )

            SELECT  n.nspname AS function_schema
                ,   p.proname AS function_name
                ,   pg_get_function_arguments(p.oid) AS function_arguments
                ,   format('CREATE AGGREGATE %s (SFUNC = %s, STYPE = %s%s%s%s%s)'
                    , format('%s.%s(%s)', n.nspname, p.proname, pg_get_function_arguments(p.oid))
                    , r.aggtransfn
                    , r.aggtranstype::regtype
                    , ', SORTOP = '    || NULLIF(r.aggsortop, 0)::regoper
                    , ', INITCOND = '  || quote_nullable(r.agginitval)
                    , ', FINALFUNC = ' || NULLIF(r.aggfinalfn, 0)
                    , CASE WHEN r.aggfinalextra THEN ', FINALFUNC_EXTRA' END
            --         add more to cover special cases like moving-aggregate etc.
                    ) AS create_statement
                ,   t.typname AS return_type
                ,   l.lanname AS function_language
            FROM pg_aggregate r
                LEFT JOIN pg_proc p ON p.oid = aggfnoid
                LEFT JOIN pg_namespace n ON p.pronamespace = n.oid
                LEFT JOIN pg_language l ON p.prolang = l.oid
                LEFT JOIN pg_type t ON t.oid = p.prorettype
                LEFT JOIN extension_functions ef ON p.oid = ef.extension_function_oid
            WHERE n.nspname NOT IN ('pg_catalog', 'information_schema') 
                AND ef.extension_function_oid IS NULL -- Filter out functions from extensions
                AND n.nspname = :schema
            """
            + (PG_GTE_11 if pg_version >= 110000 else "")
        ).bindparams(schema=schema)

        rows = sess.execute(sql)
        db_aggregates = [cls.from_sql(x[3]) for x in rows]

        for agg in db_aggregates:
            assert agg is not None

        return db_aggregates
