import contextlib
import os
import shutil
from argparse import Namespace
from io import StringIO
from pathlib import Path

from alembic import command
from alembic.config import Config
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Connection, Engine, text
from sqlalchemy.orm import scoped_session, sessionmaker

REPO_ROOT = Path(os.path.abspath(os.path.dirname(__file__))).parent.resolve()


@contextlib.contextmanager
def test_session(bind: Connection, **kw):
    kw.setdefault("join_transaction_mode", "create_savepoint")
    tx = bind.begin()
    yield scoped_session(sessionmaker(bind=bind, **kw))
    tx.rollback()


@contextlib.contextmanager
def alembic_migration(db: SQLAlchemy, alembic_cfg_path: Path):
    clear_migrations(db.engine, alembic_cfg_path)

    revision_args = {"autogenerate": True, "rev_id": "1", "message": "create"}
    revision(db.engine, alembic_cfg_path, **revision_args)
    upgrade(db.engine, alembic_cfg_path, revision="head")

    yield

    downgrade(db.engine, alembic_cfg_path, revision="base")
    clear_migrations(db.engine, alembic_cfg_path)


@contextlib.contextmanager
def alembic_config(cmd: str, engine: Engine, alembic_cfg_path: Path, **kw):
    cmd_opts = Namespace(command=cmd, **kw)

    alembic_cfg = Config(alembic_cfg_path / "alembic.ini", cmd_opts=cmd_opts)
    alembic_cfg.set_main_option("script_location", str(alembic_cfg_path))
    alembic_cfg.set_main_option("sqlalchemy.url", engine.url.render_as_string(False))

    with engine.begin() as connection:
        alembic_cfg.attributes["connection"] = connection
        yield alembic_cfg
        connection.close()


def revision(engine: Engine, alembic_cfg_path: Path, **kw):
    stdout = StringIO()
    with alembic_config("revision", engine, alembic_cfg_path, **kw) as cfg:
        with contextlib.redirect_stdout(stdout):
            command.revision(cfg, **kw)
    return stdout.getvalue()


def upgrade(engine: Engine, alembic_cfg_path: Path, **kw):
    stdout = StringIO()
    with alembic_config("upgrade", engine, alembic_cfg_path, **kw) as cfg:
        with contextlib.redirect_stdout(stdout):
            command.upgrade(cfg, **kw)
    return stdout.getvalue()


def downgrade(engine: Engine, alembic_cfg_path: Path, **kw):
    stdout = StringIO()
    with alembic_config("downgrade", engine, alembic_cfg_path, **kw) as cfg:
        with contextlib.redirect_stdout(stdout):
            command.upgrade(cfg, **kw)
    return stdout.getvalue()


def clear_migrations(engine: Engine, alembic_cfg_path: Path, **kw):
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE;"))
        connection.execute(text("DROP SCHEMA IF EXISTS audit CASCADE;"))
        connection.execute(text("CREATE SCHEMA public;"))

    versions_root = alembic_cfg_path / "versions"
    versions_root.mkdir(exist_ok=True, parents=True)
    shutil.rmtree(versions_root)
    versions_root.mkdir(exist_ok=True, parents=True)
