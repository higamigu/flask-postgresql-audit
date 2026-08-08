# Flask-PostgreSQL-Audit

![BuildStatus](https://github.com/higamigu/flask-postgresql-audit/actions/workflows/test.yml/badge.svg?branch=main)
[![VersionStatus](https://img.shields.io/pypi/v/flask-postgresql-audit.svg)](https://pypi.org/project/flask-postgresql-audit/)

Auditing extension for Flask-SQLAlchemy with PostgreSQL.
Forked from [PostgreSQL-Audit](https://github.com/kvesteri/postgresql-audit), tries to combine the best of breed from existing solutions such as
[SQLAlchemy-Continuum](https://github.com/kvesteri/SQLAlchemy-Continuum),
[Papertrail](https://github.com/airblade/paper_trail) and especially
[Audit Trigger by 2ndQuadrant](https://github.com/2ndQuadrant/audit-trigger).

-   Stores audit recordss into single table called `pga_activity`
-   Uses trigger based approach to keep INSERTs, UPDATEs
    and DELETEs as fast as possible
-   Tracks and stores actor identities into table called `pga_transaction`
-   Uses Alembic and Alembic-Utils to generate necessary database objects for migration

## Installation
```
pip install flask-postgresql-audit
```
or using `uv`
```
uv add flask-postgresql-audit
```
or install directly from this repo
```
uv add git+https://github.com/higamigu/flask-postgresql-audit --tag v1.1.0
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

## Querying Activity History

Instead of querying `audit.Activity` manually, you can use `fetch_activity()` to retrieve the audit trail for a model class, a single model instance, or a sequence/list of model instances:

``` python
# Query activity for a specific model class (e.g. Article)
stmt = audit.fetch_activity(Article)
activities = db.session.execute(stmt).all()

# Query activity for a specific article instance
stmt = audit.fetch_activity(article)
activities = db.session.execute(stmt).all()

# Query activity for multiple instances
stmt = audit.fetch_activity([article1, article2])
activities = db.session.execute(stmt).all()
```

The returned statement is a SQLAlchemy `select` object that joins `Activity` and `Transaction` tables, ordered by activity ID descending. You can further customize or execute this statement.

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

## Troubleshooting

### Activity not being recorded?

1. **Check triggers are installed**: Run `flask db upgrade` after installing the extension
2. **Verify audit is initialized**: Ensure you called `audit.init_app(app, db)` before using models
3. **Commit after changes**: Audit records are only created on `db.session.commit()`

### Actor tracking not working?

The default actor ID getter tries to import `flask_login.current_user`. If you're not using Flask-Login:

1. Provide your own `actor_id_getter` function:
   ```python
   def my_actor_id():
       return current_user.id if current_user.is_authenticated else None
   ```

2. Pass it to the extension: `audit = PostgreSQLAudit(actor_id_getter=my_actor_id)`

### Using a custom schema?

1. Set schema when creating audit: `audit = PostgreSQLAudit(schema_name="my_schema")`
2. Configure Alembic to track multiple schemas (see "Different Schema" section)
3. Add `"include_schemas=True"` to `alembic/env.py` in `run_migrations_online()`

### Fetching activity for custom models?

The `fetch_activity()` method works with:
- A model class: `audit.fetch_activity(MyModel)`
- A single instance: `audit.fetch_activity(my_instance)`
- Multiple instances: `audit.fetch_activity([instance1, instance2])`

## Extensions

### Document Staging

The `document_staging` extension adds workflow capabilities to your models:

```python
from flask_postgresql_audit.extensions.document_staging import (
    attach_listener,
    DocumentStaging,
)

class Article(DocumentStaging):
    __tablename__ = 'article'
    docstatus = Column('docstatus', Enum(Draft, Submitted, Cancelled))

# Attach the listener to your audit instance
audit.extensions['document_staging'] = attach_listener()
```

See `DocumentStaging` model for available status values (`DRAFT`, `SUBMITTED`, `CANCELLED`).

### pg_aggregate (alembic_utils)

The `pg_aggregate` extension enables custom PostgreSQL aggregate functions to be managed by Alembic migrations. It's automatically registered when using the Alembic Plugin API.

See `flask_postgresql_audit/extensions/alembic_utils/pg_aggregate.py` for implementation details.

## Running the tests

    git clone https://github.com/higamigu/flask-postgresql-audit.git
    cd flask-postgresql-audit
    pip install tox
    createdb postgresql_audit_test
    tox