# PostgreSQL-Audit (README OBSOLETE, NEED UPDATE)

![Build
Status](https://github.com/kvesteri/postgresql-audit/actions/workflows/test.yml/badge.svg?branch=master)
[![Version
Status](https://img.shields.io/pypi/v/PostgreSQL-Audit.svg)](https://pypi.python.org/pypi/PostgreSQL-Audit/)
[![Downloads](https://img.shields.io/pypi/dm/PostgreSQL-Audit.svg)](https://pypi.python.org/pypi/PostgreSQL-Audit/)

Auditing extension for PostgreSQL. Provides additional extensions for
SQLAlchemy and Flask. PostgreSQL-Audit tries to combine the best of
breed from existing solutions such as
[SQLAlchemy-Continuum](https://github.com/kvesteri/SQLAlchemy-Continuum),
[Papertrail](https://github.com/airblade/paper_trail) and especially
[Audit Trigger by 2nd
Quadrant](https://github.com/2ndQuadrant/audit-trigger).

Compared to existing solutions PostgreSQL-Audit has the following
charasteristics:

-   Stores all versions into single table called \'activity\'

-   Uses minimalistic trigger based approach to keep INSERTs, UPDATEs
    and DELETEs as fast as possible

-   

    Tracks actor IDs to be able to answer these questions quickly:

    :   -   Who modified record x on day x?
        -   What did person x do between y and z?
        -   Can you show me the activity history of record x?

[Documentation](https://postgresql-audit.readthedocs.io/en/stable/index.html)

## Installation

    pip install PostgreSQL-Audit

## Running the tests

    git clone https://github.com/kvesteri/postgresql-audit.git
    cd postgresql-audit
    pip install tox
    createdb postgresql_audit_test
    tox

## Flask extension

``` python
from postgresql_audit.flask import versioning_manager

from my_app.extensions import db


versioning_manager.init(db.Model)


class Article(db.Model):
    __tablename__ = 'article'
    __versioned__ = {}  # <- IMPORTANT!
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String)


article = Article(name='Some article')
db.session.add(article)
db.session.commit()
```

Now we can check the newly created activity.

``` python
Activity = versioning_manager.activity_cls

activity = Activity.query.first()
activity.id             # 1
activity.table_name     # 'article'
activity.verb           # 'insert'
activity.old_data       # None
activity.changed_data   # {'id': '1', 'name': 'Some article'}
```

``` python
article.name = 'Some other article'
db.session.commit()

activity = Activity.query.order_by(db.desc(Activity.id)).first()
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

activity = Activity.query.order_by(db.desc(Activity.id)).first()
activity.id             # 3
activity.table_name     # 'article'
activity.verb           # 'delete'
activity.object_id      # 1
activity.old_data       # {'id': '1', 'name': 'Some other article'}
activity.changed_data   # None
```
