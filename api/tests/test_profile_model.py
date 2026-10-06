import uuid

from sqlalchemy import select

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
