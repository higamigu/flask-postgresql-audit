import inspect
import typing as t
from contextlib import contextmanager
from itertools import groupby

import sqlalchemy as sa
import sqlalchemy.event as event
import sqlalchemy.orm as orm
from alembic_utils.replaceable_entity import ReplaceableEntity
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.util import OrderedSet

from .alembic import register_triggers, setup_db
from .models import activity_model_factory, transaction_model_factory
from .typing import AnyAttrribute
from .utils import load_template

if t.TYPE_CHECKING:
    from sqlalchemy.sql.functions import _FunctionGenerator


class ImproperlyConfigured(Exception):
    pass


class Audit:
    __audit_args__: dict = {}
    __audit_schema__: str = ""

    __audit_relid__: orm.Mapped[int]
    __audit_rowkey__: orm.Mapped[list[str]]

    __audit_configured__: t.ClassVar[bool]

    if t.TYPE_CHECKING:
        __table__: sa.Table
        __tablename__: str

        def __init__(self, **kw: t.Any): ...

    def __init_subclass__(cls, *args, **kwargs) -> None:
        if not hasattr(cls, "__audit_args__"):
            cls.__audit_args__ = {}

        event.listen(orm.Mapper, "mapper_configured", cls.__init_audit__)
        super().__init_subclass__(*args, **kwargs)

    @classmethod
    def __init_audit__(cls, mapper: orm.Mapper[t.Self], class_: type[t.Self]):
        is_configured = getattr(class_, "__audit_configured__", False)
        has_schema = hasattr(class_, "__audit_schema__")
        if not is_configured and has_schema:
            fn_ = sa.func
            if class_.__audit_schema__ and class_.__audit_schema__ != "public":
                fn_ = getattr(sa.func, class_.__audit_schema__)

            table = class_.__table__
            jsonb = sa.func.to_jsonb(table.table_valued())

            relid = orm.column_property(fn_.get_table_relid(class_.__tablename__))
            rowkey = orm.column_property(fn_.get_pk_values(relid, jsonb))

            mapper.add_property("__audit_relid__", relid)
            mapper.add_property("__audit_rowkey__", rowkey)

            class_.__audit_configured__ = True


def get_modified_columns(obj: orm.DeclarativeBase):
    modified: set[sa.ColumnElement[t.Any]] = set()
    mapper = sa.inspect(obj.__class__)
    for key, attr in sa.inspect(obj).attrs.items():
        if key in mapper.synonyms.keys():
            continue
        if not attr.history.has_changes():
            continue

        cls_attr: AnyAttrribute = getattr(obj.__class__, key)
        prop = cls_attr.property
        if isinstance(prop, orm.ColumnProperty):
            modified.update(prop.columns)
        if isinstance(prop, orm.RelationshipProperty) and prop.local_remote_pairs:
            modified.update([local for local, _ in prop.local_remote_pairs])
    return modified


def get_audit_models(registry: orm.registry):
    models: set[type[Audit]] = set()
    for mapper in registry.mappers:
        if issubclass(mapper.class_, Audit):
            models.add(mapper.class_)
    return models


def inject_model_metadata(models: t.Iterable[type[Audit]], **kwargs):
    kwargs.setdefault("schema", "public")

    for m in models:
        for k, v in kwargs.items():
            setattr(m, f"__audit_{k}__", v)


def is_object_modified(obj: object):
    if isinstance(obj, Audit):
        excluded = set(obj.__class__.__audit_args__.get("exclude", []))
        modified = {col.name for col in get_modified_columns(obj)}  # type: ignore
        return bool(modified - excluded)
    return False


def is_session_modified(session: orm.Session):
    return any(
        is_object_modified(obj) or obj in session.deleted
        for obj in session
        if isinstance(obj, Audit)
    )


def _default_actor_id() -> int | str | None:
    try:
        from flask_login import current_user  # type: ignore
    except ImportError:
        return None

    try:
        return current_user.id
    except AttributeError:
        return None


def _default_client_addr() -> str | None:
    try:
        from flask import request
    except ImportError:
        return None
    return (request and request.remote_addr) or None


class PostgreSQLAudit:
    pg_audit_classes: set[type[Audit]]
    pg_audit_enabled: bool
    pg_audit_entities: OrderedSet[ReplaceableEntity]

    options: dict[str, t.Any]

    def __init__(
        self,
        *,
        actor_cls: t.Optional[str] = None,
        actor_id_getter: t.Callable[[], t.Any] = _default_actor_id,
        client_address_getter: t.Callable[[], t.Any] = _default_client_addr,
        schema_name: t.Optional[str] = None,
        **kw,
    ):
        self._actor_cls = actor_cls
        self.schema_name = schema_name

        self.get_actor_id = actor_id_getter
        self.get_client_addr = client_address_getter

        self.options = kw

    @property
    def context(self):
        ctx = dict(schema_name=self.schema_name or "public")
        ctx["schema_prefix"] = f"{ctx['schema_name']}."
        ctx["revoke_cmd"] = f"REVOKE ALL ON {ctx['schema_prefix']}activity FROM public;"
        if "jsonb_subtract_verbose" in self.options:
            ctx["jsonb_subtract_join_type"] = "FULL"
        return ctx

    @property
    def func(self) -> "_FunctionGenerator":
        if self.schema_name and self.schema_name != "public":
            return getattr(sa.func, self.schema_name)
        return sa.func

    @contextmanager
    def disable(self, session: orm.Session | orm.scoped_session[t.Any]):
        session.execute(self.set_local("'false'"))
        self.pg_audit_enabled = False
        try:
            yield
        finally:
            self.pg_audit_enabled = True
            session.execute(self.set_local("'true'"))

    def set_local(self, value: t.Any, var: str = "enable_audit"):
        return sa.text(f"SET LOCAL flask_pga.{var} = {value}")

    def render_tmpl(self, tmpl_name: str, **kwargs):
        return load_template(tmpl_name).substitute(**self.context)

    def receive_do_orm_execute(self, orm_execute_state: orm.ORMExecuteState):
        if (
            orm_execute_state.is_insert
            or orm_execute_state.is_update
            or orm_execute_state.is_delete
        ) and any(
            isinstance(mapper.class_, Audit) for mapper in orm_execute_state.all_mappers
        ):
            self.insert_transaction(orm_execute_state.session)

    def receive_before_flush(self, session: orm.Session, flush_context, instances):
        if is_session_modified(session):
            self.insert_transaction(session)

    def insert_transaction(self, session: orm.Session):
        if self.pg_audit_enabled:
            values = {
                "native_transaction_id": sa.func.txid_current(),
                "issued_at": sa.text("NOW() AT TIME ZONE 'UTC'"),
                "client_addr": self.get_client_addr(),
                "actor_id": self.get_actor_id(),
            }

            session.execute(
                pg_insert(self.Transaction)
                .values(**values)
                .on_conflict_do_nothing(
                    constraint="pga_transaction_unique_native_tx_id"
                )
            )

    @property
    def actor_cls(self) -> type | None:
        if isinstance(self._actor_cls, str):
            if not self.Base:
                raise ImproperlyConfigured(
                    "This manager does not have declarative base set up yet. "
                    "Call init method to set up this manager."
                )
            try:
                return self.Base.registry._class_registry[self._actor_cls]  # type: ignore
            except KeyError:
                raise ImproperlyConfigured(
                    "Could not build relationship between PGAuditActivity"
                    f" and {self._actor_cls}. {self._actor_cls} was not found in declarative class "
                    "registry. Either configure VersioningManager to "
                    "use different actor class or disable this "
                    "relationship by setting it to None."
                )
        return self._actor_cls

    def attach_listeners(self):
        event.listen(orm.Session, "before_flush", self.receive_before_flush)
        event.listen(orm.Session, "do_orm_execute", self.receive_do_orm_execute)

    def remove_listeners(self):
        event.remove(orm.Session, "before_flush", self.receive_before_flush)
        event.remove(orm.Session, "do_orm_execute", self.receive_do_orm_execute)

    def register_triggers(self):
        register_triggers(self)

    def setup_db(self):
        setup_db(self)

    def init_app(self, app: Flask, db: SQLAlchemy, **kwargs):
        self.pg_audit_enabled = True
        self.pg_audit_entities = OrderedSet()

        self.Base: type["orm.DeclarativeBase"] = db.Model  # type: ignore

        self.Transaction = transaction_model_factory(
            self.Base,
            actor_cls=self.actor_cls,
            schema_name=self.schema_name,
            **kwargs,
        )

        self.Activity = activity_model_factory(
            self.Base,
            transaction_cls=self.Transaction,
            schema_name=self.schema_name,
            **kwargs,
        )

        self.pg_audit_classes = get_audit_models(self.Base.registry)
        inject_model_metadata(self.pg_audit_classes, schema=self.schema_name)

        self.setup_db()
        self.attach_listeners()

        app.extensions["postgresql-audit"] = self

    def fetch_activity(self, obj: type[Audit] | Audit | t.Sequence[Audit]):
        stmt = (
            sa.select(
                self.Activity.id,
                self.Activity.verb,
                self.Activity.table_name,
                self.Activity.issued_at.label("activity_timestamp"),
                self.Transaction.issued_at.label("transaction_timestamp"),
                self.Transaction.client_addr.label("transaction_addr"),
                self.Transaction.actor_id.label("transaction_actor"),
                self.Activity.old_data,
                self.Activity.changed_data,
            )
            .select_from(self.Activity)
            .join(self.Transaction)
            .order_by(self.Activity.id.desc())
        )

        if inspect.isclass(obj):
            class_ = obj
            stmt = stmt.filter(self.Activity.table_name == class_.__tablename__)
            stmt = stmt.filter(self.Activity.row_key == class_.__audit_rowkey__)

        else:
            objects = list(obj) if isinstance(obj, t.Sequence) else list([obj])
            conditions = []
            for class_, objs in groupby(objects, key=lambda o: o.__class__):
                conditions.append(
                    sa.and_(
                        self.Activity.table_name == class_.__tablename__,
                        self.Activity.row_key.in_([o.__audit_rowkey__ for o in objs]),
                    )
                )

            if len(conditions) == 1:
                stmt = stmt.filter(conditions[0])
            else:
                stmt = stmt.filter(sa.or_(*conditions))

        return stmt
