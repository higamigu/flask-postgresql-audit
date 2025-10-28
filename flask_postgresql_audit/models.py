import typing as t

import sqlalchemy as sa
from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.orm import declared_attr, mapped_column, relationship

from .base import ActivityBase, TransactionBase
from .typing import OMap

if t.TYPE_CHECKING:
    from sqlalchemy.orm import DeclarativeBase, Mapper

    T = t.TypeVar("T")
    TBase = t.TypeVar("TBase", bound=type[DeclarativeBase])


class PGAuditFactoryError(Exception):
    pass


def activity_model_factory(
    base_cls: "type[DeclarativeBase]",
    transaction_cls: type[TransactionBase],
    activity_base: type[ActivityBase] = ActivityBase,
    schema_name: str | None = None,
    **kwargs,
):
    class PGAuditActivity(base_cls, activity_base):
        __tablename__ = "pga_activity"
        __table_args__ = {"schema": schema_name}

        transaction_id = mapped_column(sa.BigInteger, sa.ForeignKey(transaction_cls.id))
        transaction = relationship(transaction_cls, backref="activities")

    return PGAuditActivity


def transaction_model_factory(
    base_cls: "type[DeclarativeBase]",
    actor_cls: type | None = None,
    transaction_base: type[TransactionBase] = TransactionBase,
    schema_name: str | None = None,
    **kwargs,
):
    if actor_cls:
        actor_mapper: "Mapper[DeclarativeBase]" = sa.inspect(actor_cls)
        if len(actor_mapper.primary_key) != 1:
            raise PGAuditFactoryError(
                "PGAudit does not support actor class"
                f"with composite PK: {actor_cls.__name__}"
            )

        actor_pk = actor_mapper.primary_key[0]

    class PGAuditTransaction(base_cls, transaction_base):
        __tablename__ = "pga_transaction"

        @declared_attr
        def actor_id(cls) -> OMap[t.Any]:
            if actor_cls:
                return mapped_column(actor_pk.type, ForeignKey(actor_pk))
            return mapped_column(sa.Text)

        if actor_cls:
            actor = relationship(actor_cls, viewonly=True)

        @declared_attr.directive
        @classmethod
        def __table_args__(cls):
            return (
                ExcludeConstraint(
                    (cls.native_transaction_id, "="),
                    (cls.__transaction_interval__(), "&&"),
                    name="pga_transaction_unique_native_tx_id",
                ),
                {"schema": schema_name},
            )

    return PGAuditTransaction
