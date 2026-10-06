from sqlalchemy import text


def test_database_is_reachable(db_session, require_db):
    assert db_session.execute(text("select 1")).scalar() == 1
