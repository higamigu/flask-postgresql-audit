# Flask-PostgreSQL-Audit

![BuildStatus](https://github.com/higamigu/flask-postgresql-audit/actions/workflows/test.yml/badge.svg?branch=main)
[![VersionStatus](https://img.shields.io/pypi/v/PostgreSQL-Audit.svg)](https://pypi.python.org/pypi/PostgreSQL-Audit/)
[![Downloads](https://img.shields.io/pypi/dm/PostgreSQL-Audit.svg)](https://pypi.python.org/pypi/PostgreSQL-Audit/)

Auditing extension for Flask-SQLAlchemy with PostgreSQL.
Forked from [PostgreSQL-Audit](https://github.com/kvesteri/postgresql-audit), tries to combine the best of breed from existing solutions such as
[SQLAlchemy-Continuum](https://github.com/kvesteri/SQLAlchemy-Continuum),
[Papertrail](https://github.com/airblade/paper_trail) and especially
[Audit Trigger by 2ndQuadrant](https://github.com/2ndQuadrant/audit-trigger).

-   Stores audit recordss into single table called \'pga_activity\'
-   Uses stateful trigger based approach to keep INSERTs, UPDATEs
    and DELETEs as fast as possible
-   Tracks and stores actor identities into table called \'pga_transaction\'
-   Uses Alembic and Alembic-Utils to generate necessary database objects

## Installation
```
uv add
```
or install directly from this repo
```
uv add git+https://github.com/higamigu/flask-postgresql-audit --tag v1.0.0
```

## Usage

``` python
from flask_sqlalchemy import SQLAlchemy
from flask_postgresql_audit import PostgreSQLAudit, Audit

from my_app import app  # your flask app

db = SQLAlchemy()
audit = PostgreSQLAudit()

class Article(db.Model, Audit):
    __tablename__ = 'article'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String)

db.init_app(app)
audit.init_app(app, db)

article = Article(name='Some article')
db.session.add(article)
db.session.commit()
```
Then generate migration file
```
flask db migrate -m "pg audit initial migration"
flask db upgrade
```

Now we can check the newly created activity.

``` python
activity = db.session.scalar(select(audit.Activity))
activity.id             # 1
activity.table_name     # 'article'
activity.verb           # 'insert'
activity.old_data       # None
activity.changed_data   # {'id': '1', 'name': 'Some article'}
```

``` python
article.name = 'Some other article'
db.session.commit()

activity = db.session.scalar(select(audit.Activity).order_by(desc("id")))
activity.id             # 2
activity.table_name     # 'article'
activity.verb           # 'update'
activity.object_id      # 1
activity.old_data       # {'id': '1', 'name': 'Some article'}
activity.changed_data   # {'name': 'Some other article'}
```

``` python
db.session.delete(article)
db.session.commit()

activity = db.session.scalar(select(audit.Activity).order_by(desc("id")))
activity.id             # 3
activity.table_name     # 'article'
activity.verb           # 'delete'
activity.object_id      # 1
activity.old_data       # {'id': '1', 'name': 'Some other article'}
activity.changed_data   # None
```

## Different Schema
You can isolate `pg_audit` objects entirely to a different schema by doing

``` python
from flask_postgresql_audit import PostgreSQLAudit

audit = PostgreSQLAudit(schema="audit")

...
```
And then you need to tell alembic to track other than `public` schema by adding following line in `alembic/env.py`
``` python
...

def run_migrations_online():
    connectable = get_engine()

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=get_metadata(),
            include_schemas=True, # add this arg
            ...
        )

        with context.begin_transaction():
            context.run_migrations()

...
```

## Custom Actor ID getter
You can customize actor id getter function by doing the following. Here is an example using `current_user` from `flask_jwt_extended` library.

``` python
from flask_jwt_extended import jwt_required, current_user

@jwt_required(optional=True)
def actor_id_getter():
    try:
        return current_user.email or None
    except Exception:
        return None

...

audit = PostgreSQLAudit(actor_id_getter=actor_id_getter)

...
```

## Enable Alembic Logger
You can enable alembic logger for `pg_audit` by adding the following to your `alembic.ini`
``` ini
# Logging configuration
[loggers]
keys = root,sqlalchemy,alembic,alembic_utils,pg_audit # add 'pg_audit' here

...

[logger_pg_audit]  # and add the logger for pg_audit here
level = INFO
handlers =
qualname = pg_audit
```

## Running the tests

    git clone https://github.com/higamigu/flask-postgresql-audit.git
    cd flask-postgresql-audit
    pip install tox
    createdb postgresql_audit_test
    tox