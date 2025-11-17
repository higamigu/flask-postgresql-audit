import pytest
import sqlalchemy as sa

from .app import User, audit, db


@pytest.mark.usefixtures("test_client")
class TestCustomSchemaactivityCreation:
    def test_insert(self, user):
        stmt = sa.select(audit.Activity).limit(1)
        if activity := db.session.scalar(stmt):
            assert activity.row_key == ["1"]
            assert activity.old_data == {}
            assert activity.changed_data == {"id": user.id, "name": "John", "age": 15}
            assert activity.table_name == "user"
            assert activity.native_transaction_id > 0  # type: ignore
            assert activity.verb == "insert"

    def test_activity_after_commit(self):
        user = User(name="Jack")
        db.session.add(user)
        db.session.commit()
        user = User(name="Jack")
        db.session.add(user)
        db.session.commit()

        stmt = sa.select(sa.func.count()).select_from(audit.Activity)
        assert db.session.scalar(stmt) == 2

    def test_activity_after_rollback(self):
        user = User(name="John")
        db.session.add(user)
        db.session.rollback()
        user = User(name="John")
        db.session.add(user)
        db.session.commit()

        stmt = sa.select(sa.func.count()).select_from(audit.Activity)
        assert db.session.scalar(stmt) == 1

    def test_data_expression(self, user):
        user.name = "Luke"
        db.session.commit()

        stmt = sa.select(audit.Activity).where(
            audit.Activity.table_name == "user",
            sa.or_(
                audit.Activity.old_data["id"].astext == str(user.id),
                audit.Activity.changed_data["id"].astext == str(user.id),
            ),
        )

        assert len(db.session.scalars(stmt).all()) == 2
