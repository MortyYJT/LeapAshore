import uuid

from sqlalchemy import select, text

from app.models.client import Client, Profile


def test_client_and_profile_round_trip(db_session, require_db):
    client_id = str(uuid.uuid4())
    db_session.add(Client(id=client_id))
    db_session.add(Profile(client_id=client_id, school_name="北京邮电大学", domestic_tier="211"))
    db_session.commit()

    row = db_session.execute(
        select(Profile).where(Profile.client_id == client_id)
    ).scalar_one()
    assert row.school_name == "北京邮电大学"
    assert row.domestic_tier == "211"
    # Fields the applicant never filled in stay null rather than defaulting to a guess.
    assert row.gpa_score is None

    db_session.delete(row)
    db_session.delete(db_session.get(Client, client_id))
    db_session.commit()


def test_deleting_a_client_removes_its_profile(db_session, require_db):
    client_id = str(uuid.uuid4())
    db_session.add(Client(id=client_id))
    db_session.add(Profile(client_id=client_id))
    db_session.commit()

    db_session.delete(db_session.get(Client, client_id))
    db_session.commit()

    assert db_session.get(Profile, client_id) is None


def test_the_database_cascade_removes_the_profile_without_the_orm(db_session, require_db):
    """The `profiles.client_id` foreign key must carry ON DELETE CASCADE in the database.

    The test above only proves that the ORM cleans up: `cascade="all, delete-orphan"` makes
    SQLAlchemy emit its own DELETE for the profile before the client row goes, so it would still
    pass if the migration had been built without `ondelete="CASCADE"`. Task 4 deletes rows without
    the ORM, so the constraint itself has to be exercised. This deletes the client with raw SQL on
    the session, which SQLAlchemy's unit of work never sees, and then asks a fresh statement whether
    the profile survived. Without the constraint the DELETE is rejected outright by Postgres and the
    profile row stays behind, so this test fails.
    """
    client_id = str(uuid.uuid4())
    db_session.add(Client(id=client_id))
    db_session.add(Profile(client_id=client_id))
    db_session.commit()

    # Raw SQL on the session: the ORM's delete-orphan cascade cannot run, so only the database
    # constraint can remove the profile row.
    db_session.execute(text("DELETE FROM clients WHERE id = :client_id"), {"client_id": client_id})
    db_session.commit()

    surviving_profiles = db_session.execute(
        text("SELECT count(*) FROM profiles WHERE client_id = :client_id"),
        {"client_id": client_id},
    ).scalar_one()
    assert surviving_profiles == 0

    # Leave nothing behind if the constraint is missing, so the test stays repeatable.
    db_session.execute(text("DELETE FROM profiles WHERE client_id = :client_id"), {"client_id": client_id})
    db_session.execute(text("DELETE FROM clients WHERE id = :client_id"), {"client_id": client_id})
    db_session.commit()
