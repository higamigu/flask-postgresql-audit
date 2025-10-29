import os
from typing import TYPE_CHECKING, Any

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Table
from sqlalchemy.orm import Mapped, mapped_column

from flask_postgresql_audit import Audit, PostgreSQLAudit


class DefaultConfig:
    DB_USER = os.environ.get("POSTGRESQL_AUDIT_TEST_USER", "postgres")
    DB_PASSWORD = os.environ.get("POSTGRESQL_AUDIT_TEST_PASSWORD", "")
    DB_NAME = os.environ.get("POSTGRESQL_AUDIT_TEST_DB", "postgresql_audit_test")

    SQLALCHEMY_DATABASE_URI = (
        f"postgresql://{DB_USER}:{DB_PASSWORD}@localhost/{DB_NAME}"
    )
    SQLALCHEMY_ECHO = False


db = SQLAlchemy()
audit = PostgreSQLAudit()


class BaseModel(db.Model):
    __abstract__: bool = True

    if TYPE_CHECKING:
        __table__: Table
        __tablename__: str

        __table_args__: tuple | dict

        def __init__(self, **kw: Any): ...


class User(BaseModel, Audit):
    __tablename__ = "user"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    age: Mapped[int | None]


class Article(BaseModel, Audit):
    __tablename__ = "article"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]


app = Flask(__name__)

app.config.from_object(DefaultConfig)
app.secret_key = "secret"
app.debug = True

db.init_app(app)
audit.init_app(app, db)
