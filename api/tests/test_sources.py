import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.source import Source, SourceStatus, SourceVersion


def test_source_starts_unverified(db_session, require_db):
    """A source must never claim verification it has not had."""
    source = Source(
        id=str(uuid.uuid4()),
        url="https://immi.homeaffairs.gov.au/visas/getting-a-visa/visa-listing/student-500/genuine-student-requirement",
        title="Genuine Student requirement",
        publisher="Department of Home Affairs",
        domain="immi.homeaffairs.gov.au",
    )
    db_session.add(source)
    db_session.commit()

    assert source.status == SourceStatus.UNVERIFIED
    assert source.verified_at is None

    db_session.delete(source)
    db_session.commit()


def test_source_url_is_unique(db_session, require_db):
    url = f"https://example.edu.au/{uuid.uuid4()}"
    db_session.add(Source(id=str(uuid.uuid4()), url=url, title="a"))
    db_session.commit()

    db_session.add(Source(id=str(uuid.uuid4()), url=url, title="b"))
    try:
        db_session.commit()
    except IntegrityError:
        db_session.rollback()
    else:
        raise AssertionError("a duplicate source url was accepted")


def test_versions_are_numbered_within_a_source(db_session, require_db):
    source = Source(id=str(uuid.uuid4()), url=f"https://example.edu.au/{uuid.uuid4()}", title="a")
    db_session.add(source)
    db_session.commit()

    db_session.add(SourceVersion(id=str(uuid.uuid4()), source_id=source.id, version_no=1))
    db_session.commit()
    db_session.add(SourceVersion(id=str(uuid.uuid4()), source_id=source.id, version_no=2))
    db_session.commit()

    numbers = db_session.execute(
        select(SourceVersion.version_no)
        .where(SourceVersion.source_id == source.id)
        .order_by(SourceVersion.version_no)
    ).scalars().all()
    assert numbers == [1, 2]

    db_session.delete(source)
    db_session.commit()
