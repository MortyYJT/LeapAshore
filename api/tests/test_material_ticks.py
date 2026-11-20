"""Per-material ticks on an application record, through the HTTP routes (PRD-multi-device 3.7).

The catalogue materials used here are made up for the test and removed afterwards.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.db import SessionLocal
from app.main import app
from app.models.program import Program, ProgramMaterial
from app.models.source import Source
from app.seed import seed_programs
from tests.test_seed import PROGRAM_IDS
from tests.versioned import create_record, patch_record, put_portfolio

pytestmark = pytest.mark.usefixtures("require_db")

PAGE = "https://example.test/fixture/apply"
ENTRIES = [
    ("recommendation", "recommendation", 2, None, "FIXTURE PAGE: Two letters of recommendation are required."),
    ("personal_statement", "personal_statement", None, "up to 500 words", "FIXTURE PAGE: A statement of up to 500 words."),
    ("other", "other", None, "course descriptions", "FIXTURE PAGE: Describe each core course."),
    ("other-2", "other", None, "passport copy", "FIXTURE PAGE: A copy of your passport."),
]


@pytest.fixture
def programs():
    """Two seeded programs: the first with four made-up collected materials, the second not read."""
    with SessionLocal() as s:
        seed_programs(s)
        read, unread = PROGRAM_IDS[0], PROGRAM_IDS[1]
        held = {pid: s.get(Program, pid).materials_snapshot_sha256 for pid in (read, unread)}
        s.execute(delete(ProgramMaterial).where(ProgramMaterial.program_id.in_([read, unread])))
        s.get(Program, read).materials_snapshot_sha256 = "9" * 64
        s.get(Program, unread).materials_snapshot_sha256 = None
        for order, (key, kind, count, note, quote) in enumerate(ENTRIES):
            s.add(ProgramMaterial(id=str(uuid.uuid4()), program_id=read, key=key, type=kind, count=count, note=note,
                                  quote=quote, source_url=PAGE, sort_order=order))
        s.commit()
    yield {"read": read, "unread": unread}
    with SessionLocal() as s:
        s.execute(delete(ProgramMaterial).where(ProgramMaterial.program_id.in_([read, unread])))
        for pid, sha in held.items():
            s.get(Program, pid).materials_snapshot_sha256 = sha
        s.commit()


def tick(client: TestClient, key: str, ticks: dict[str, bool]):
    """Tick or clear materials the way the page does: each new tick with the digest it read."""
    record = next(r for r in client.get("/api/application-records").json() if r["id"] == key)
    digests = {m["key"]: m["digest"] for m in record["materials"]}
    basis = {k: digests[k] for k, wanted in ticks.items() if wanted and k in digests}
    return patch_record(client, key, {"materialTicks": ticks, "materialBasis": basis})


def applicant(*program_ids: str) -> tuple[TestClient, dict[str, dict]]:
    client = TestClient(app)
    assert put_portfolio(client, [{"programId": pid, "tier": "稳"} for pid in program_ids]).status_code == 200
    return client, {row["programId"]: row for row in client.get("/api/application-records").json()}


def test_a_record_lists_the_collected_materials_unticked_with_their_source(programs):
    _client, rows = applicant(programs["read"], programs["unread"])
    read, unread = rows[programs["read"]], rows[programs["unread"]]

    assert read["materialsExtracted"] is True
    assert [(m["key"], m["type"], m["count"], m["note"], m["ready"], m["changed"]) for m in read["materials"]] == [
        ("recommendation", "recommendation", 2, None, False, False),
        ("personal_statement", "personal_statement", None, "up to 500 words", False, False),
        ("other", "other", None, "course descriptions", False, False),
        ("other-2", "other", None, "passport copy", False, False),
    ]
    assert read["materials"][0]["quote"] == ENTRIES[0][4] and read["materials"][0]["sourceUrl"] == PAGE
    assert (read["materialsDone"], read["materialsTotal"], read["materialsReady"]) == (0, 4, False)
    # Not read yet: no list, and the flag says so. It is not an empty list of requirements.
    assert unread["materialsExtracted"] is False and unread["materials"] == []
    assert (unread["materialsDone"], unread["materialsTotal"], unread["materialsReady"]) == (0, 0, False)


def test_a_catalogue_record_names_the_program_s_official_page(programs):
    """A page that was read and lists no documents has no entry to carry a source, so the record
    itself says where the program's page is; a manual record has no such page."""
    with SessionLocal() as s:
        page = s.get(Source, s.get(Program, programs["unread"]).source_id).url
        # Read, lists none: the snapshot is recorded and there are no entries.
        s.get(Program, programs["unread"]).materials_snapshot_sha256 = "8" * 64
        s.commit()
    client, rows = applicant(programs["read"], programs["unread"])
    silent = rows[programs["unread"]]
    assert silent["materialsExtracted"] is True and silent["materials"] == []
    assert silent["programUrl"] == page and page.startswith("http")
    assert rows[programs["read"]]["programUrl"].startswith("http")
    # The page comes with every way a record is served: the answer to an edit too.
    edited = patch_record(client, silent["id"], {"customMaterials": [{"id": "c-1", "label": "成绩单"}]})
    assert edited.status_code == 200 and edited.json()["programUrl"] == page

    manual = create_record(client, {"school": "Example University", "name": "Example MSc"}).json()
    assert manual["programUrl"] is None


def test_ticks_are_set_and_cleared_one_material_at_a_time(programs):
    client, rows = applicant(programs["read"])
    key = rows[programs["read"]]["id"]

    ticked = tick(client, key, {"recommendation": True, "other-2": True})
    assert ticked.status_code == 200
    assert [m["ready"] for m in ticked.json()["materials"]] == [True, False, False, True]
    assert (ticked.json()["materialsDone"], ticked.json()["materialsReady"]) == (2, False)

    # A key left out keeps its state; false clears.
    after = tick(client, key, {"recommendation": False, "other": True}).json()
    assert [m["ready"] for m in after["materials"]] == [False, False, True, True]

    everything = tick(client, key, {m["key"]: True for m in after["materials"]}).json()
    assert (everything["materialsDone"], everything["materialsTotal"], everything["materialsReady"]) == (4, 4, True)


def test_a_tick_on_a_material_the_catalogue_does_not_list_is_refused(programs):
    client, rows = applicant(programs["read"], programs["unread"])
    for program, key in ((programs["read"], "portfolio"), (programs["unread"], "recommendation")):
        response = tick(client, rows[program]["id"], {key: True})
        assert response.status_code == 422 and "没有" in response.json()["detail"]
    assert all(not m["ready"] for row in client.get("/api/application-records").json() for m in row["materials"])


def test_a_manual_application_has_only_the_applicant_s_own_checklist():
    client = TestClient(app)
    key = create_record(client, {"school": "Example University", "name": "Example MSc"}).json()["id"]

    assert tick(client, key, {"cv": True}).status_code == 422
    saved = patch_record(client, key, {"customMaterials": [
        {"id": "c-1", "label": " 在读证明 ", "done": True}, {"id": "c-2", "label": "作品集"}]})
    assert saved.status_code == 200
    body = saved.json()
    assert body["customMaterials"] == [{"id": "c-1", "label": "在读证明", "done": True}, {"id": "c-2", "label": "作品集", "done": False}]
    assert body["materialsExtracted"] is False and body["materials"] == []
    assert (body["materialsDone"], body["materialsTotal"], body["materialsReady"]) == (1, 2, False)

    # The list is replaced as a whole: sending one line removes the other.
    assert patch_record(client, key, {"customMaterials": [{"id": "c-2", "label": "作品集", "done": True}]}).json()["materialsReady"] is True
    # An edit that does not mention the checklist leaves it alone.
    assert patch_record(client, key, {"round": "Round 1"}).json()["customMaterials"] == [{"id": "c-2", "label": "作品集", "done": True}]


@pytest.mark.parametrize("lines", [
    [{"id": "recommendation", "label": "推荐信"}],          # an id from the catalogue's namespace
    [{"id": "c-1", "label": "  "}],                        # no label
    [{"id": "c-1", "label": "A"}, {"id": "c-1", "label": "B"}],  # the same line twice
    [{"id": "c-1", "label": "A", "extra": 1}],             # an unknown field
    [{"id": f"c-{n}", "label": "A"} for n in range(41)],   # too many
])
def test_a_malformed_checklist_is_refused(lines):
    client = TestClient(app)
    key = create_record(client, {"school": "Example University", "name": "Example MSc"}).json()["id"]
    assert patch_record(client, key, {"customMaterials": lines}).status_code == 422
    assert client.get("/api/application-records").json()[0]["customMaterials"] == []


def test_the_old_single_flag_is_no_longer_accepted():
    """A page loaded before the change still sends `materialsReady`; it is told, not silently ignored."""
    client = TestClient(app)
    key = create_record(client, {"school": "Example University", "name": "Example MSc"}).json()["id"]
    assert patch_record(client, key, {"materialsReady": True}).status_code == 422
    assert create_record(client, {"school": "Another", "name": "MSc", "materialsReady": True}).status_code == 422


def test_a_tick_based_on_a_stale_version_is_refused_with_the_stored_record(programs):
    """Two devices: the phone ticks one material, the laptop then ticks another from the version it
    read before. The laptop gets 409 and the phone's tick; nothing of the laptop's is written."""
    client, rows = applicant(programs["read"])
    record = rows[programs["read"]]
    path = f"/api/application-records/{record['id']}"

    digest = {m["key"]: m["digest"] for m in record["materials"]}
    phone = client.patch(path, json={"materialTicks": {"recommendation": True}, "materialBasis": {"recommendation": digest["recommendation"]},
                                     "baseVersion": record["version"]})
    assert phone.status_code == 200
    laptop = client.patch(path, json={"materialTicks": {"other": True}, "materialBasis": {"other": digest["other"]},
                                      "baseVersion": record["version"]})

    assert laptop.status_code == 409 and laptop.json()["code"] == "stale_version"
    current = laptop.json()["current"]
    assert [m["ready"] for m in current["materials"]] == [True, False, False, False]
    assert current["version"] == phone.json()["version"] != record["version"]
    # Based on the stored version, the same tick is accepted and keeps the phone's.
    kept = client.patch(path, json={"materialTicks": {"other": True}, "materialBasis": {"other": digest["other"]},
                                    "baseVersion": current["version"]})
    assert [m["ready"] for m in kept.json()["materials"]] == [True, False, True, False]


def test_a_tick_without_a_base_version_is_refused(programs):
    client, rows = applicant(programs["read"])
    record = rows[programs["read"]]
    response = client.patch(f"/api/application-records/{record['id']}", json={
        "materialTicks": {"recommendation": True}, "materialBasis": {"recommendation": record["materials"][0]["digest"]}})
    assert response.status_code == 422


def test_a_tick_must_say_which_wording_it_is_for(programs):
    client, rows = applicant(programs["read"])
    response = patch_record(client, rows[programs["read"]]["id"], {"materialTicks": {"recommendation": True}})
    assert response.status_code == 422 and "materialBasis" in response.json()["detail"]
    # Clearing a tick needs none.
    assert patch_record(client, rows[programs["read"]]["id"], {"materialTicks": {"recommendation": False}}).status_code == 200


def test_a_tick_for_a_wording_the_catalogue_no_longer_holds_is_refused_as_stale(programs):
    """The page was opened, the catalogue was imported again (two letters became three), and the
    applicant ticks what the old page shows. The record's own version did not move, so the version
    check alone would accept it and store "three letters: ready"."""
    client, rows = applicant(programs["read"])
    record = rows[programs["read"]]
    with SessionLocal() as s:
        row = s.scalar(select(ProgramMaterial).where(ProgramMaterial.program_id == programs["read"], ProgramMaterial.key == "recommendation"))
        row.count, row.quote = 3, "FIXTURE PAGE: Three letters of recommendation are required."
        s.commit()

    response = client.patch(f"/api/application-records/{record['id']}", json={
        "materialTicks": {"recommendation": True}, "materialBasis": {"recommendation": record["materials"][0]["digest"]},
        "baseVersion": record["version"]})

    assert response.status_code == 409 and response.json()["code"] == "stale_version"
    current = response.json()["current"]
    assert (current["materials"][0]["count"], current["materials"][0]["ready"]) == (3, False)
    assert current["version"] == record["version"], "nothing was written, not even the overlay row"
    stored = client.get("/api/application-records").json()[0]
    assert stored["materials"][0]["ready"] is False and stored["materialsDone"] == 0
    # Ticked again for the wording the server now holds, it is accepted.
    again = client.patch(f"/api/application-records/{record['id']}", json={
        "materialTicks": {"recommendation": True}, "materialBasis": {"recommendation": current["materials"][0]["digest"]},
        "baseVersion": current["version"]})
    assert again.status_code == 200 and again.json()["materials"][0]["ready"] is True


def test_a_tick_moves_the_version_and_a_restated_one_does_not(programs):
    client, rows = applicant(programs["read"])
    key = rows[programs["read"]]["id"]
    first = tick(client, key, {"recommendation": True}).json()
    again = tick(client, key, {"recommendation": True}).json()
    assert first["version"] != rows[programs["read"]]["version"]
    assert again["version"] == first["version"]


def test_a_tick_does_not_count_once_the_requirement_changes_and_can_be_given_again(programs):
    client, rows = applicant(programs["read"])
    key = rows[programs["read"]]["id"]
    assert tick(client, key, {"recommendation": True}).json()["materials"][0]["ready"] is True

    with SessionLocal() as s:  # the catalogue is imported again and the page now asks for three
        row = s.scalar(select(ProgramMaterial).where(ProgramMaterial.program_id == programs["read"], ProgramMaterial.key == "recommendation"))
        row.count, row.quote = 3, "FIXTURE PAGE: Three letters of recommendation are required."
        s.commit()

    changed = client.get("/api/application-records").json()[0]
    assert (changed["materials"][0]["ready"], changed["materials"][0]["changed"], changed["materialsDone"]) == (False, True, 0)
    again = tick(client, key, {"recommendation": True}).json()["materials"][0]
    assert (again["ready"], again["changed"], again["count"]) == (True, False, 3)


def test_ticks_on_entries_the_catalogue_dropped_are_forgotten_with_the_next_edit(programs):
    client, rows = applicant(programs["read"])
    key = rows[programs["read"]]["id"]
    tick(client, key, {"other-2": True, "recommendation": True})
    with SessionLocal() as s:
        s.execute(delete(ProgramMaterial).where(ProgramMaterial.program_id == programs["read"], ProgramMaterial.key == "other-2"))
        s.commit()

    after = tick(client, key, {"other": True}).json()

    assert [(m["key"], m["ready"]) for m in after["materials"]] == [
        ("recommendation", True), ("personal_statement", False), ("other", True)]
    assert (after["materialsDone"], after["materialsTotal"]) == (2, 3)


def test_another_applicant_s_ticks_are_their_own(programs):
    first, rows = applicant(programs["read"])
    second, others = applicant(programs["read"])
    tick(first, rows[programs["read"]]["id"], {"recommendation": True})
    assert second.get("/api/application-records").json()[0]["materials"][0]["ready"] is False
