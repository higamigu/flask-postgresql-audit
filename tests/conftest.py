import pytest

from tests.utils import REPO_ROOT, alembic_migration, test_session

from .app import Article, User, app, db

ALEMBIC_CONFIG = REPO_ROOT / "tests/migrations"


@pytest.fixture(scope="session")
def test_client():
    test_client = app.test_client()
    with app.app_context():
        with alembic_migration(db, ALEMBIC_CONFIG):
            yield test_client


@pytest.fixture(autouse=True)
def join_transaction_mode(test_client):
    with db.engine.connect() as connection:
        with test_session(connection) as session:
            db.session = session
            yield
            db.session.close()


@pytest.fixture
def article():
    article = Article(name="Some article")
    db.session.add(article)
    db.session.commit()
    yield article


@pytest.fixture
def user():
    user = User(name="John", age=15)
    db.session.add(user)
    db.session.commit()
    yield user
