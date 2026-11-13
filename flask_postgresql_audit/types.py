from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Dialect


class XID8(sa.types.UserDefinedType[int]):
    """PostgreSQL 64-bit transaction identifier (``xid8``)."""

    cache_ok = True

    def get_col_spec(self, **kw: Any) -> str:
        return "xid8"

    def bind_processor(self, dialect: Dialect):
        def process(value: int | None) -> str | None:
            return str(value) if value is not None else None

        return process

    def result_processor(self, dialect: Dialect, coltype: Any):
        def process(value: str | int | None) -> int | None:
            return int(value) if value is not None else None

        return process

    @property
    def python_type(self) -> type[int]:
        return int
