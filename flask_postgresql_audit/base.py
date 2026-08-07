from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, Text, func, text
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

from .typing import OMap


class ActivityBase:
    if TYPE_CHECKING:
        transaction_id: Mapped[int]
        transaction: Mapped["TransactionBase"]

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    schema_name: OMap[str] = mapped_column(Text)
    table_name: OMap[str] = mapped_column(Text)

    relid: OMap[int]
    issued_at: OMap[datetime]
    native_transaction_id: OMap[int] = mapped_column(BigInteger, index=True)
    verb: OMap[str] = mapped_column(Text)

    row_key: OMap[list[str]] = mapped_column(JSONB, default=[], server_default="[]")
    old_data: OMap[dict] = mapped_column(JSONB, default={}, server_default="{}")
    changed_data: OMap[dict] = mapped_column(JSONB, default={}, server_default="{}")

    def __repr__(self):
        return (
            f"<{self.__class__.__name__} table_name={self.table_name!r} id={self.id!r}>"
        )


class TransactionBase:
    if TYPE_CHECKING:
        actor_id: declared_attr[Any]

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    native_transaction_id: OMap[int] = mapped_column(BigInteger)
    issued_at: OMap[datetime]
    client_addr: OMap[str] = mapped_column(INET)

    @classmethod
    def __transaction_interval__(cls):
        interval = text("INTERVAL '1 hour'")
        return func.tsrange(cls.issued_at - interval, cls.issued_at)

    def __repr__(self):
        return (
            f"<{self.__class__.__name__} id={self.id!r} issued_at={self.issued_at!r}>"
        )
