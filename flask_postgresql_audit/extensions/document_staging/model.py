import typing as t
from datetime import datetime

import sqlalchemy as sa
import sqlalchemy.event as event
import sqlalchemy.orm as orm
from flask_sqlalchemy.session import Session
from sqlalchemy.dialects.postgresql import ENUM as PGEnum

from flask_postgresql_audit.typing import OMap

from .enum import Docstatus


class DocumentStaging:
    __staging_configured__: t.ClassVar[bool]
    __staging_fk_keys__: t.ClassVar[list[sa.ColumnClause[t.Any]]]

    __bump_transitions__: t.ClassVar[dict[Docstatus, Docstatus]] = {
        Docstatus.DRAFT: Docstatus.SUBMITTED,
        Docstatus.SUBMITTED: Docstatus.CANCELLED,
    }

    __unique_docstatus__: t.ClassVar[list[Docstatus]] = [
        Docstatus.DRAFT,
        Docstatus.SUBMITTED,
        Docstatus.CANCELLED,
    ]

    if t.TYPE_CHECKING:
        __table__: sa.Table
        __tablename__: str

        def __init__(self, **kw: t.Any): ...

    def __init_subclass__(cls, *args, **kwargs) -> None:
        event.listen(cls, "instrument_class", cls.__init_staging__)
        super().__init_subclass__(*args, **kwargs)

    @classmethod
    def __init_staging__(cls, mapper: orm.Mapper[t.Self], class_: type[t.Self]):
        if not getattr(class_, "__staging_configured__", False):
            table = class_.__table__

            pk_cols = []
            fk_cols = []

            for pk in table.primary_key.columns:
                fk_name = f"revision_{pk.name}"
                fk = table.c.get(fk_name) or sa.Column(fk_name, pk.type, nullable=True)

                if fk.name not in table.columns:
                    table.append_column(fk)

                if not hasattr(class_, fk.name):
                    setattr(class_, fk.name, orm.mapped_column(pk.type, nullable=True))

                pk_cols.append(pk)
                fk_cols.append(fk)

            fk_const = sa.ForeignKeyConstraint(
                fk_cols,
                pk_cols,
                name=f"{class_.__tablename__}_revision_fkey",
                ondelete="SET NULL",
            )

            if fk_const.name not in table.constraints:
                table.append_constraint(fk_const)

            class_.__staging_fk_keys__ = fk_cols
            class_.__staging_configured__ = True

    docstatus: orm.Mapped[Docstatus] = orm.mapped_column(
        PGEnum(Docstatus, name="docstatus_enum", create_type=True),
        default=Docstatus.DRAFT,
    )

    created_on: OMap[datetime] = orm.mapped_column(default=sa.func.now())
    created_by: OMap[str]

    submitted_by: OMap[str]
    submitted_on: OMap[datetime]

    cancelled_by: OMap[str]
    cancelled_on: OMap[datetime]

    @orm.declared_attr
    @classmethod
    def revision(cls) -> "orm.Mapped[t.Self]":
        return orm.relationship(cls, uselist=False)

    @orm.declared_attr
    @classmethod
    def revision_of(cls) -> "orm.Mapped[t.Self]":
        return orm.relationship(
            cls,
            uselist=False,
            remote_side=lambda: list(cls.__table__.primary_key.columns),
            back_populates="revision",
        )

    def bump(self):
        if self.docstatus not in self.__bump_transitions__:
            msg = f"Invalid docstatus: {self.docstatus.name} cannot be bumped"
            raise ValueError(msg)
        self.docstatus = self.__bump_transitions__[self.docstatus]

    def revise(self, new_doc: t.Self):
        if self.docstatus != Docstatus.CANCELLED:
            msg = f"Invalid docstatus: {self.docstatus.name} cannot be revised"
            raise ValueError(msg)
        self.docstatus = Docstatus.REVISED
        self.revision = new_doc
        return new_doc

    def delete(self, session: orm.scoped_session[Session]):
        if self.docstatus != Docstatus.DRAFT:
            msg = f"Invalid docstatus: {self.docstatus.name} cannot be deleted"
            raise ValueError(msg)
        session.delete(self)
        if parent := self.revision_of:
            parent.docstatus = Docstatus.CANCELLED
