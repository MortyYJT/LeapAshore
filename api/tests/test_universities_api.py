"""The school list the library joins its 287 schools against, and reading one school's programs."""

from fastapi.testclient import TestClient

from app.main import app
from app.seed import seed_programs
from app.seed_catalog import seed_catalog


def _seeded(db_session) -> TestClient:
    seed_programs(db_session)
    seed_catalog(db_session)
    return TestClient(app)


def test_every_school_is_listed_with_its_program_counts(require_db, db_session):
    body = _seeded(db_session).get("/api/universities").json()

    usyd = next(u for u in body if u["id"] == "usyd")
    assert usyd["name"] == "悉尼大学"
    assert usyd["country"] == "澳大利亚"
    assert usyd["programCount"] > 0
    assert 0 <= usyd["withRequirementsCount"] <= usyd["programCount"]
    assert set(usyd) == {"id", "name", "nameEn", "country", "programCount", "withRequirementsCount"}


def test_a_school_with_several_ids_can_be_read_in_one_request(require_db, db_session):
    client = _seeded(db_session)
    usyd = client.get("/api/programs", params={"provider": "usyd", "limit": 1})
    unsw = client.get("/api/programs", params={"provider": "unsw", "limit": 1})

    both = client.get("/api/programs", params={"provider": "usyd,unsw", "limit": 1})

    assert int(both.headers["X-Total-Count"]) == int(usyd.headers["X-Total-Count"]) + int(
        unsw.headers["X-Total-Count"]
    )
