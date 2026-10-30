"""The admin's verification entry (openspec source-verification): who may, what it shows, what it writes,
and the database guard that refuses every other way of setting `sources.verified_at`."""

import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.exc import DBAPIError

from app import roles
from app.collect.importer import import_school, program_id_for, source_id_for
from app.config import settings
from app.db import SessionLocal
from app.models.account import Account
from app.models.client import Client
from app.models.program import Program, ProgramDeadline, ProgramPrerequisite, University
from app.models.snapshot import SnapshotChunk, SnapshotPage
from app.models.source import Source, SourceStatus, SourceVerification, SourceVersion
from app.services import source_verification as sv
from tests.auth_helpers import login, login_mode, new_client, outbox, unique_email  # noqa: F401

ADMIN = "/api/admin/verification"
SHA = "a" * 64
NEWER = "b" * 64
SHARED_URL = "https://verify.example/admissions"


def uid(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:10]}"


@pytest.fixture
def page(require_db):
    """One imported page backing one program, with its version's quotes and its snapshot in chunks."""
    university = uid("test-verify-")
    url = f"https://verify.example/{uuid.uuid4().hex[:8]}/msc"
    source_id = str(uuid.uuid4())
    program_id = uid("test-verify-msc-")
    with SessionLocal() as s:
        s.add(University(id=university, name="核验测试大学", name_en="Verify Test University", country="英国"))
        s.add(Source(id=source_id, url=url, title="MSc Verification", publisher=university, domain="verify.example"))
        s.flush()
        s.add(SourceVersion(
            id=str(uuid.uuid4()), source_id=source_id, version_no=1, content_sha256=SHA,
            fetched_at=datetime(2026, 10, 29, 1, tzinfo=UTC),
            body_text="[academic] a 2:1 honours degree in computing\n[ielts] IELTS 7.0 with 6.5 in each component\n"
                      f"[china_requirement] 80% (211) or 85% (出处: {SHARED_URL})",
        ))
        s.add(Program(
            id=program_id, university_id=university, name="核验理学硕士", name_en="MSc Verification",
            english_requirement="IELTS 7.0，单项不低于 6.5", academic_requirement="2:1 honours in computing",
            minimum_mark=80, non_211_minimum_mark=85, source_id=source_id, data_status="机器核对",
        ))
        s.flush()
        s.add(ProgramPrerequisite(id=str(uuid.uuid4()), program_id=program_id, label="linear algebra",
                                  category="collected", sort_order=0))
        s.add(ProgramDeadline(id=str(uuid.uuid4()), program_id=program_id, label="Round 1",
                              deadline=date(2027, 1, 15), quote="Round 1 closes 15 January 2027",
                              source_url=url, sort_order=0))
        for page_url, sha, program, lines in (
            (url, SHA, program_id, ["Entry requirements", "a 2:1 honours degree in computing",
                                    "IELTS 7.0 with 6.5 in each component", "Round 1 closes 15 January 2027"]),
            (SHARED_URL, "c" * 64, None, ["Chinese applicants: 80% (211) or 85%"]),
        ):
            existing = s.scalar(select(SnapshotPage).where(SnapshotPage.url == page_url))
            if existing is not None:
                continue
            page_id = str(uuid.uuid4())
            s.add(SnapshotPage(id=page_id, url=page_url, school_key=university, university_id=university,
                               program_id=program, title="page", snapshot_sha256=sha,
                               fetched_at=datetime(2026, 10, 29, 1, tzinfo=UTC), content_sha256="d" * 64,
                               chunker="test", chunk_count=2))
            s.flush()
            s.add(SnapshotChunk(id=str(uuid.uuid4()), page_id=page_id, ordinal=0, text="\n".join(lines[:2]),
                                content_sha256="e" * 64))
            s.add(SnapshotChunk(id=str(uuid.uuid4()), page_id=page_id, ordinal=1, text="\n".join(lines[2:]) or "-",
                                content_sha256="f" * 64))
        s.commit()
    yield {"source": source_id, "program": program_id, "url": url, "university": university}
    with SessionLocal() as s:
        s.execute(delete(SnapshotPage).where(SnapshotPage.url.in_([url, SHARED_URL])))
        s.execute(delete(Program).where(Program.id == program_id))
        s.execute(delete(Source).where(Source.id == source_id))
        s.execute(delete(University).where(University.id == university))
        s.commit()


def account(outbox, *, admin: bool):  # noqa: F811
    client = new_client()
    email = unique_email()
    login(client, outbox, email)
    with SessionLocal() as s:
        if admin:
            roles.grant(s, email)
        client.account_id = s.scalar(select(Account.id).where(Account.email == email))
    client.email = email
    return client


@pytest.fixture
def admin(login_mode):  # noqa: F811
    return account(login_mode, admin=True)


def source_row(source_id: str) -> Source:
    with SessionLocal() as s:
        return s.get(Source, source_id)


# ---- who may ---------------------------------------------------------------------------------------------


def test_every_admin_route_is_refused_in_anonymous_mode(page, monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", False)
    client = new_client()
    for method, path in (("get", "/api/admin/me"), ("get", ADMIN), ("get", f"{ADMIN}/{page['source']}"),
                         ("post", f"{ADMIN}/{page['source']}/verify"), ("post", f"{ADMIN}/{page['source']}/revoke")):
        response = getattr(client, method)(path, **({"json": {"contentSha256": SHA}} if method == "post" else {}))
        assert response.status_code == 403, (path, response.status_code)
    assert source_row(page["source"]).verified_at is None


def test_without_a_session_401_and_as_an_applicant_403(page, login_mode):  # noqa: F811
    assert new_client().get(ADMIN).status_code == 401
    applicant = account(login_mode, admin=False)
    assert applicant.get("/api/admin/me").status_code == 403
    assert applicant.get(f"{ADMIN}/{page['source']}").status_code == 403
    assert applicant.post(f"{ADMIN}/{page['source']}/verify", json={"contentSha256": SHA}).status_code == 403
    assert source_row(page["source"]).verified_at is None


def test_the_admin_is_told_who_they_are(admin):
    assert admin.get("/api/admin/me").json() == {"email": admin.email, "role": "admin"}


# ---- what it shows ---------------------------------------------------------------------------------------


def test_the_list_finds_the_page_by_its_program_and_filters_by_state(admin, page):
    listed = admin.get(ADMIN, params={"q": "MSc Verification"}).json()
    row = next(item for item in listed["items"] if item["sourceId"] == page["source"])
    assert row["url"] == page["url"] and row["status"] == "待核验" and row["verifiedAt"] is None
    assert row["school"] == "核验测试大学" and [p["id"] for p in row["programs"]] == [page["program"]]
    assert row["snapshotReady"] is True and listed["total"] >= 1
    verified = admin.get(ADMIN, params={"q": "MSc Verification", "status": "verified"}).json()
    assert all(item["sourceId"] != page["source"] for item in verified["items"])


def test_the_reading_view_shows_each_field_with_its_quotes_and_the_snapshot(admin, page):
    detail = admin.get(f"{ADMIN}/{page['source']}").json()
    assert detail["source"]["status"] == "待核验" and detail["version"]["contentSha256"] == SHA
    program = detail["programs"][0]
    fields = {f["key"]: f for f in program["fields"]}
    assert fields["english"]["values"] == ["IELTS 7.0，单项不低于 6.5"]
    assert fields["english"]["quotes"] == [{"text": "IELTS 7.0 with 6.5 in each component", "sourceUrl": None}]
    assert fields["academic"]["quotes"][0]["text"] == "a 2:1 honours degree in computing"
    assert fields["china"]["values"] == ["211 院校均分 80", "其他院校均分 85"]
    assert fields["china"]["quotes"] == [{"text": "80% (211) or 85%", "sourceUrl": SHARED_URL}]
    assert fields["prerequisites"]["values"] == ["linear algebra"] and fields["prerequisites"]["quotes"] == []
    assert fields["deadlines"]["values"] == ["Round 1：2027-01-15"]
    assert fields["deadlines"]["quotes"] == [{"text": "Round 1 closes 15 January 2027", "sourceUrl": None}]
    own, shared = detail["pages"]
    assert own["url"] == page["url"] and own["matchesVersion"] is True and own["own"] is True
    assert "IELTS 7.0 with 6.5 in each component" in own["text"]
    assert shared["url"] == SHARED_URL and shared["own"] is False and "80% (211) or 85%" in shared["text"]
    assert detail["canVerify"] is True and detail["history"] == []


def test_an_unknown_or_unimported_page_is_404(admin):
    assert admin.get(f"{ADMIN}/{uuid.uuid4()}").status_code == 404


# ---- what it writes --------------------------------------------------------------------------------------


def test_confirming_the_version_read_marks_the_page_verified_and_records_who(admin, page):
    response = admin.post(f"{ADMIN}/{page['source']}/verify", json={"contentSha256": SHA})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source"]["status"] == "已核验" and body["source"]["verifiedAt"]
    assert body["history"][0]["action"] == "verify" and body["history"][0]["by"] == admin.email
    stored = source_row(page["source"])
    assert stored.status == SourceStatus.VERIFIED and stored.verified_at is not None
    with SessionLocal() as s:
        row = s.scalars(select(SourceVerification).where(SourceVerification.source_id == page["source"])).one()
    assert row.account_id == admin.account_id and row.decided_at == stored.verified_at and row.content_sha256 == SHA
    # The applicant-facing catalogue now says a person checked the page.
    served = new_client().get("/api/programs", params={"ids": page["program"]}).json()
    assert served[0]["source"]["status"] == "已核验"
    # A second confirmation is refused rather than overwriting the first moment.
    assert admin.post(f"{ADMIN}/{page['source']}/verify", json={"contentSha256": SHA}).status_code == 409


def test_a_confirmation_of_another_version_is_refused(admin, page):
    response = admin.post(f"{ADMIN}/{page['source']}/verify", json={"contentSha256": NEWER})
    assert response.status_code == 409
    with SessionLocal() as s:
        s.add(SourceVersion(id=str(uuid.uuid4()), source_id=page["source"], version_no=2, content_sha256=NEWER))
        s.commit()
    # The page changed after the admin opened it: the sha they read is no longer the latest.
    assert admin.post(f"{ADMIN}/{page['source']}/verify", json={"contentSha256": SHA}).status_code == 409
    # And the new version has no snapshot to read yet.
    assert admin.get(f"{ADMIN}/{page['source']}").json()["canVerify"] is False
    assert admin.post(f"{ADMIN}/{page['source']}/verify", json={"contentSha256": NEWER}).status_code == 409
    assert source_row(page["source"]).verified_at is None


def test_a_withdrawal_returns_the_page_to_unverified_and_keeps_the_history(admin, page):
    assert admin.post(f"{ADMIN}/{page['source']}/revoke").status_code == 409  # nothing to withdraw
    admin.post(f"{ADMIN}/{page['source']}/verify", json={"contentSha256": SHA})
    body = admin.post(f"{ADMIN}/{page['source']}/revoke").json()
    assert body["source"]["status"] == "待核验" and body["source"]["verifiedAt"] is None
    assert [h["action"] for h in body["history"]] == ["revoke", "verify"]
    assert source_row(page["source"]).verified_at is None


def test_deleting_the_admin_keeps_the_fact_and_drops_who(admin, page):
    admin.post(f"{ADMIN}/{page['source']}/verify", json={"contentSha256": SHA})
    with SessionLocal() as s:
        client_id = s.scalar(select(Account.client_id).where(Account.id == admin.account_id))
        s.execute(delete(Client).where(Client.id == client_id))  # how an account is deleted
        s.commit()
        history = sv.detail(s, page["source"])["history"]
    assert history[0]["action"] == "verify" and history[0]["by"] is None
    assert source_row(page["source"]).verified_at is not None


# ---- the database guard ----------------------------------------------------------------------------------


def refused(statement) -> bool:
    with SessionLocal() as s:
        try:
            statement(s)
            s.commit()
        except DBAPIError as error:
            s.rollback()
            return "verified_at" in str(error) or "已核验" in str(error)
    return False


def test_the_database_refuses_a_date_set_by_the_orm_raw_sql_or_an_insert(page):
    def orm(s):
        row = s.get(Source, page["source"])
        row.status, row.verified_at = SourceStatus.VERIFIED, datetime.now(UTC)

    def raw(s):
        s.execute(text("UPDATE sources SET status = '已核验', verified_at = now() WHERE id = :id"), {"id": page["source"]})

    def insert(s):
        s.add(Source(id=str(uuid.uuid4()), url=f"https://verify.example/{uuid.uuid4()}", title="t",
                     status=SourceStatus.VERIFIED, verified_at=datetime.now(UTC)))

    def status_only(s):
        s.execute(text("UPDATE sources SET status = '已核验' WHERE id = :id"), {"id": page["source"]})

    for statement in (orm, raw, insert, status_only):
        assert refused(statement), statement.__name__
    assert source_row(page["source"]).verified_at is None


def test_a_confirmation_row_unlocks_only_an_admins_date_in_the_same_transaction(page, login_mode):  # noqa: F811
    applicant = account(login_mode, admin=False)
    admin = account(login_mode, admin=True)
    moment = datetime.now(UTC)

    def by(account_id, *, same_transaction=True):
        def statement(s):
            s.add(SourceVerification(id=str(uuid.uuid4()), source_id=page["source"], action="verify",
                                     content_sha256=SHA, account_id=account_id, decided_at=moment))
            if not same_transaction:
                s.commit()
            s.flush()
            s.execute(text("UPDATE sources SET status = '已核验', verified_at = :at WHERE id = :id"),
                      {"at": moment, "id": page["source"]})
        return statement

    assert refused(by(applicant.account_id))
    assert refused(by(None))
    assert refused(by(admin.account_id, same_transaction=False))  # a row left by an earlier transaction
    assert source_row(page["source"]).verified_at is None
    assert not refused(by(admin.account_id))  # what the service does
    assert source_row(page["source"]).verified_at == moment


def test_clearing_the_date_is_always_allowed(admin, page):
    admin.post(f"{ADMIN}/{page['source']}/verify", json={"contentSha256": SHA})
    with SessionLocal() as s:
        s.execute(text("UPDATE sources SET status = '待核验', verified_at = NULL WHERE id = :id"), {"id": page["source"]})
        s.commit()
    assert source_row(page["source"]).verified_at is None


# ---- the importer never sets it, and keeps a person's confirmation while the page is unchanged ----------


KEY = "test-verify-importer"
URL = "https://verify.example/importer-msc"


def importer_file(sha: str) -> dict:
    return {
        "school_key": KEY, "school_name_en": "Verify Importer University", "country": "United Kingdom",
        "listing_urls": ["https://verify.example/courses"],
        "programs": [{
            "name": "MSc Importer", "url": URL, "snapshot_sha256": sha, "fetched_at": "2026-10-29T01:00:00+00:00",
            "fields": {"ielts": {"overall": 7.0, "quote": "IELTS 7.0 overall", "check": "ok"}}, "status": "机器核对",
        }],
    }


@pytest.fixture
def imported(admin, tmp_path):
    schools = {KEY: {"school_key": KEY, "name_zh": "核验导入大学", "country": "United Kingdom"}}
    with SessionLocal() as s:
        import_school(s, importer_file(SHA), schools, root=tmp_path)
        s.add(SnapshotPage(id=str(uuid.uuid4()), url=URL, school_key=KEY, university_id=KEY, title="p",
                           snapshot_sha256=SHA, content_sha256="d" * 64, chunker="test", chunk_count=1))
        s.flush()
        page_id = s.scalar(select(SnapshotPage.id).where(SnapshotPage.url == URL))
        s.add(SnapshotChunk(id=str(uuid.uuid4()), page_id=page_id, ordinal=0, text="IELTS 7.0 overall",
                            content_sha256="e" * 64))
        s.commit()
    yield {"schools": schools, "root": tmp_path, "source": source_id_for(URL)}
    pid = program_id_for(KEY, {"url": URL, "name": "MSc Importer"})
    with SessionLocal() as s:
        s.execute(delete(SnapshotPage).where(SnapshotPage.url == URL))
        s.execute(delete(Program).where(Program.id == pid))
        s.execute(delete(Source).where(Source.id == source_id_for(URL)))
        s.execute(delete(University).where(University.id == KEY))
        s.commit()


def test_reimporting_the_same_page_keeps_the_confirmation_and_new_content_withdraws_it(admin, imported):
    assert admin.post(f"{ADMIN}/{imported['source']}/verify", json={"contentSha256": SHA}).status_code == 200
    stamped = source_row(imported["source"]).verified_at
    with SessionLocal() as s:
        import_school(s, importer_file(SHA), imported["schools"], root=imported["root"])
    assert source_row(imported["source"]).verified_at == stamped
    with SessionLocal() as s:
        import_school(s, importer_file(NEWER), imported["schools"], root=imported["root"])
    row = source_row(imported["source"])
    assert row.verified_at is None and row.status == SourceStatus.UNVERIFIED
