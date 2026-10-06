import uuid

from fastapi.testclient import TestClient

from app.main import app

COOKIE = "offerpilot_client"


def test_first_request_creates_a_client_and_returns_an_empty_profile(require_db):
    client = TestClient(app)
    response = client.get("/api/profile")
    assert response.status_code == 200
    assert response.json()["schoolName"] is None
    assert COOKIE in response.cookies or COOKIE in client.cookies


def test_patch_persists_and_reads_back(require_db):
    client = TestClient(app)
    client.get("/api/profile")
    response = client.patch("/api/profile", json={"schoolName": "北京邮电大学", "gpaScore": 82})
    assert response.status_code == 200
    assert response.json()["schoolName"] == "北京邮电大学"

    again = client.get("/api/profile").json()
    assert again["schoolName"] == "北京邮电大学"
    assert float(again["gpaScore"]) == 82.0


def test_a_second_subject_cannot_see_the_first_ones_profile(require_db):
    """The core isolation guarantee: two cookies must never resolve to the same profile."""
    first = TestClient(app)
    first.patch("/api/profile", json={"schoolName": "北京邮电大学"})

    second = TestClient(app)
    assert second.get("/api/profile").json()["schoolName"] is None


def test_rejects_an_unknown_field(require_db):
    client = TestClient(app)
    response = client.patch("/api/profile", json={"gpaScoreTypo": 82})
    assert response.status_code == 422


def test_a_cookie_that_is_not_a_uuid_is_replaced_before_it_is_read(require_db):
    """A malformed cookie must be swapped for a fresh subject, and the swap must reach the client.

    The dangerous regression is subtler than a crash: if the malformed value were written into the
    `clients` row, or reused as the lookup key, one garbage cookie would keep addressing the same
    subject instead of being replaced. Assert both that the answer is a brand new empty profile and
    that the response carries a well-formed replacement cookie.
    """
    client = TestClient(app)
    client.cookies.set(COOKIE, "not-a-uuid")
    response = client.get("/api/profile")
    assert response.status_code == 200
    assert response.json()["schoolName"] is None

    replacement = response.cookies[COOKIE]
    assert replacement != "not-a-uuid"
    uuid.UUID(replacement)  # raises if the replacement is not a well-formed uuid

    # The malformed value must not have been persisted as a subject, so it is worthless to resend:
    # the next request that presents it is a stranger again, not the subject it named. The jar is
    # cleared first so this request carries the malformed value and not the replacement the server
    # just set; httpx keys jar entries by domain, so keeping both would leave two cookies with one
    # name and make the jar unreadable.
    client.cookies.clear()
    client.cookies.set(COOKIE, "not-a-uuid")
    assert client.get("/api/profile").json()["schoolName"] is None


def test_a_second_spelling_of_a_client_id_does_not_mint_a_second_profile(require_db):
    """Every valid spelling of one id must resolve to the one row it names.

    `uuid.UUID` accepts upper case and braces as the same uuid, but the column stores lower-case
    canonical text. An id pasted back in another spelling has to be canonicalised, or the same
    applicant silently acquires a second, empty profile.
    """
    owner = TestClient(app)
    owner.patch("/api/profile", json={"schoolName": "北京邮电大学"})
    client_id = owner.cookies[COOKIE]

    same_subject = TestClient(app)
    same_subject.cookies.set(COOKIE, "{" + client_id.upper() + "}")
    assert same_subject.get("/api/profile").json()["schoolName"] == "北京邮电大学"


def test_a_partial_patch_leaves_the_other_fields_alone(require_db):
    client = TestClient(app)
    client.patch(
        "/api/profile",
        json={"schoolName": "北京邮电大学", "major": "计算机科学与技术", "gpaScore": 82},
    )

    response = client.patch("/api/profile", json={"major": "软件工程"})
    assert response.status_code == 200
    body = response.json()
    assert body["major"] == "软件工程"
    assert body["schoolName"] == "北京邮电大学"
    assert float(body["gpaScore"]) == 82.0


def test_an_explicit_null_clears_the_field_it_names(require_db):
    """Only omitted fields are protected; a field the caller sends as null is a real edit."""
    client = TestClient(app)
    client.patch("/api/profile", json={"schoolName": "北京邮电大学", "major": "计算机科学与技术"})

    body = client.patch("/api/profile", json={"schoolName": None}).json()
    assert body["schoolName"] is None
    assert body["major"] == "计算机科学与技术"


def test_the_wire_format_uses_the_frontend_key_names(require_db):
    """Task 8 feeds these responses straight into the `Profile` type in web/lib/types.ts.

    The camelCase keys are part of the contract, not a detail: `educationLevel` and `targetDegree`
    are the names the frontend edits, so a profile that answers `currentEducationLevel` would leave
    those two fields permanently empty in the UI.
    """
    client = TestClient(app)
    body = client.get("/api/profile").json()

    for key in (
        "educationLevel",
        "schoolName",
        "gpaScore",
        "targetDegree",
        "targetField",
        "annualBudgetCny",
        "englishScore",
    ):
        assert key in body, key
