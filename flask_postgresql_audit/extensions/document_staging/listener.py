import typing as t
from datetime import datetime

import sqlalchemy.event as event
import sqlalchemy.orm as orm
from flask_sqlalchemy.session import Session

from flask_postgresql_audit.core import _default_actor_id

from .enum import Docstatus
from .model import DocumentStaging

_O = t.TypeVar("_O", bound=object)


def attach_listener(actor_id_getter: t.Callable[[], t.Any] = _default_actor_id):
    @event.listens_for(orm.Session, "before_flush")
    def __receive_before_flush__(
        session: Session,
        flush_context: orm.UOWTransaction,
        instances: t.Optional[t.Sequence[_O]],
    ):
        for obj in session.new:
            if isinstance(obj, DocumentStaging):
                if obj.docstatus == Docstatus.DRAFT or obj.docstatus is None:
                    obj.created_by = actor_id_getter()
                    obj.created_on = datetime.now()
        for obj in session.dirty:
            if isinstance(obj, DocumentStaging):
                if obj.docstatus == Docstatus.SUBMITTED:
                    obj.submitted_by = actor_id_getter()
                    obj.submitted_on = datetime.now()
                if obj.docstatus == Docstatus.CANCELLED:
                    obj.cancelled_by = actor_id_getter()
                    obj.cancelled_on = datetime.now()
