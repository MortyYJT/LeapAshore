"""Application materials: the checks an entry must pass, the file's block, the import and the catalogue.

Every page and every requirement in this file is made up for the test (`FIXTURE PAGE`, `example.test`);
none of it describes a real program.
"""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, event, select

from app.collect import materials
from app.collect.importer import import_materials, import_school, program_id_for, source_id_for
from app.collect.verify import SchemaError, drop_failing, verify
from app.db import engine
from app.main import app
from app.models.program import Program, ProgramMaterial, ProgramPrerequisite, University
from app.models.source import Source, SourceVersion

KEY = "test-materials-university"
SHA = "d" * 64
LINKED_SHA = "e" * 64
URL = "https://example.test/fixture/msc-made-up"
LINKED_URL = "https://example.test/fixture/how-to-apply"
SCHOOLS = {KEY: {"school_key": KEY, "name_zh": "材料测试大学", "country": "United Kingdom"}}
NAME = "MSc Made Up"

PAGE = """FIXTURE PAGE: MSc Made Up
What to send
Two letters of recommendation are required, at least one from an academic referee.
A personal statement of no more than 1,000 words.
Upload a current CV.
Official transcripts from every institution attended.
Entry requirements
A 2:1 honours degree in a numerate subject.
"""
LINKED_PAGE = """FIXTURE PAGE: how to apply
Applicants to design programmes submit a portfolio of 3 projects.
"""

RECOMMENDATION = {"type": "recommendation", "count": 2, "note": "at least one academic referee",
                  "quote": "Two letters of recommendation are required, at least one from an academic referee."}
STATEMENT = {"type": "personal_statement", "note": "no more than 1,000 words",
             "quote": "A personal statement of no more than 1,000 words."}
CV = {"type": "cv", "quote": "Upload a current CV."}


@pytest.fixture
def root(tmp_path):
    folder = tmp_path / KEY
    folder.mkdir()
    (folder / f"{SHA}.txt").write_text(PAGE, encoding="utf-8")
    (folder / f"{LINKED_SHA}.txt").write_text(LINKED_PAGE, encoding="utf-8")
    (folder / f"{LINKED_SHA}.json").write_text(json.dumps({"final_url": LINKED_URL}), encoding="utf-8")
    return tmp_path


def school_file(items=None, *, block=True, rejected=0, fields=None):
    program = {
        "name": NAME, "url": URL, "snapshot_sha256": SHA,
        "fields": {"academic": {"text": "2:1 honours", "quote": "A 2:1 honours degree in a numerate subject."}}
        if fields is None else fields,
    }
    if block:
        program["materials"] = {"snapshot_sha256": SHA, "extractor": "test", "extracted_at": "2026-11-20",
                                "rejected": rejected, "items": [dict(item) for item in (items or [])]}
    return {"school_key": KEY, "school_name_en": "Test Materials University", "country": "United Kingdom",
            "listing_urls": ["https://example.test/courses"], "programs": [program]}


def checked(items, root, **kwargs):
    return verify(school_file(items, **kwargs), root)["programs"][0]


def checks(items, root):
    return [item["check"] for item in checked(items, root)["materials"]["items"]]


# ---------------------------------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------------------------------


def test_an_entry_whose_quote_is_on_the_page_and_states_its_count_passes(root):
    assert checks([RECOMMENDATION, STATEMENT, CV], root) == ["ok", "ok", "ok"]


def test_a_quote_that_is_not_on_the_page_is_refused_with_the_reason(root):
    invented = {"type": "writing_sample", "quote": "A writing sample of 10 pages is required."}
    assert checks([invented], root) == ["quote not found in snapshot"]


def test_a_count_the_quote_does_not_state_is_refused(root):
    three = {**RECOMMENDATION, "count": 3}
    one_cv = {**CV, "count": 1}  # "a current CV" is not a stated number
    assert checks([three, one_cv], root) == ["count=3 not in quote", "count=1 not in quote"]


def test_a_count_is_read_as_digits_or_as_a_word_and_never_inside_a_longer_number(root):
    text = materials.normalize("we need 2 references. two essays are set. a sample of 12 pages. a 2.5 gpa is expected.")
    assert materials.check_material({"type": "recommendation", "count": 2, "quote": "We need 2 references."}, text) == []
    assert materials.check_material({"type": "personal_statement", "count": 2, "quote": "Two essays are set."}, text) == []
    assert materials.check_material({"type": "other", "note": "pages", "count": 2, "quote": "A sample of 12 pages."}, text) == ["count=2 not in quote"]
    assert materials.check_material({"type": "other", "note": "gpa", "count": 2, "quote": "A 2.5 GPA is expected."}, text) == ["count=2 not in quote"]


@pytest.mark.parametrize("count, quote", [
    (1, "A statement of no more than 1,000 words."),      # the 1 of 1,000
    (2, "A 2,000-word writing sample is required."),      # the 2 of 2,000
    (4, "A CV of one A4 page is required."),              # the 4 of A4
    (2, "Transcripts for the 2nd year are required."),    # the 2 of 2nd
    (2, "A GPA of 2.5 or above is expected here."),       # the 2 of 2.5
    (3, "Deadline: 3/1/2027 for all applicants."),        # the 3 of a date
])
def test_a_count_is_a_number_standing_on_its_own(count, quote):
    item = {"type": "other", "note": "fixture", "count": count, "quote": quote}
    assert materials.check_material(item, materials.normalize(quote)) == [f"count={count} not in quote"]


@pytest.mark.parametrize("count, quote", [
    (2, "Provide 2 references. Thank you."),
    (2, "References (2): academic ones."),
    (2, "Upload a 2-page writing sample."),
    (12, "Twelve copies of the form are needed."),
])
def test_a_count_written_on_its_own_is_found(count, quote):
    item = {"type": "other", "note": "fixture", "count": count, "quote": quote}
    assert materials.check_material(item, materials.normalize(quote)) == []


def test_a_number_word_in_the_note_must_be_in_the_quote_too():
    quote = "Two references are required here."
    said = {"type": "recommendation", "count": 2, "note": "three academic referees", "quote": quote}
    assert materials.check_material(said, materials.normalize(quote)) == ["note states 3, which is not in the quote"]
    assert materials.check_material({**said, "note": "two academic referees"}, materials.normalize(quote)) == []


@pytest.mark.parametrize("quote, reason", [
    ("\u200b", "no quote"),                     # invisible: folds to nothing, and nothing is on every page
    ("   ", "no quote"),
    ("2", "quote is shorter than 10 characters"),
    ("a CV", "quote is shorter than 10 characters"),
])
def test_a_quote_with_no_words_in_it_proves_nothing(quote, reason):
    item = {"type": "recommendation", "quote": quote}
    assert materials.check_material(item, materials.normalize("a page with 2 things and a CV"))[0].startswith(reason)


def test_a_figure_in_the_note_must_be_in_the_quote(root):
    stretched = {**STATEMENT, "note": "no more than 1,500 words"}
    assert checks([stretched], root) == ["note states 1500, which is not in the quote"]
    assert checks([STATEMENT], root) == ["ok"]


def test_a_type_outside_the_fixed_list_is_refused(root):
    assert "is not one of" in checks([{"type": "enrolment_certificate", "quote": "Upload a current CV."}], root)[0]


def test_an_other_entry_must_say_what_it_is(root):
    unnamed = {"type": "other", "quote": "Official transcripts from every institution attended."}
    assert checks([unnamed], root) == ["an `other` entry needs a note that names the material"]


def test_a_failing_entry_keeps_its_values(root):
    three = {**RECOMMENDATION, "count": 3}
    stored = checked([three], root)["materials"]["items"][0]
    assert {key: stored[key] for key in three} == three


def test_an_entry_quoted_from_a_linked_page_is_checked_against_that_page_and_cites_it(root):
    portfolio = {"type": "portfolio", "count": 3, "source_sha256": LINKED_SHA,
                 "quote": "Applicants to design programmes submit a portfolio of 3 projects."}
    stored = checked([portfolio], root)["materials"]["items"][0]
    assert stored["check"] == "ok" and stored["source_url"] == LINKED_URL
    # The same quote without its page is looked for on the program's own page, where it is not.
    assert checks([{k: v for k, v in portfolio.items() if k != "source_sha256"}], root) == ["quote not found in snapshot"]


def test_a_missing_snapshot_fails_every_entry(tmp_path):
    assert checks([CV], tmp_path) == ["snapshot missing"]


def test_materials_do_not_change_the_program_s_status(root):
    without = verify(school_file(block=False), root)["programs"][0]["status"]
    bad = {"type": "cv", "quote": "not on the page"}
    assert checked([bad], root)["status"] == without == "机器核对"


def test_a_block_that_is_not_a_list_of_entries_is_a_schema_error(root):
    data = school_file([CV])
    data["programs"][0]["materials"] = {"items": "CV"}
    with pytest.raises(SchemaError):
        verify(data, root)


def test_a_file_without_a_materials_block_verifies_to_the_same_bytes(root):
    """Adding the material checks must not move a byte of the 282 files that have no block."""
    import copy

    from app.collect import verify as verify_module

    data = school_file(block=False)
    after = verify(copy.deepcopy(data), root)

    def without_materials_code(payload):
        # The same run with the material step taken out: what `verify` wrote before this change.
        original = verify_module.materials.block_of
        verify_module.materials.block_of = lambda program: None
        try:
            return verify(copy.deepcopy(payload), root)
        finally:
            verify_module.materials.block_of = original

    dump = lambda value: json.dumps(value, ensure_ascii=False, indent=1).encode()  # noqa: E731
    assert dump(after) == dump(without_materials_code(data))
    assert "materials" not in after["programs"][0] and "materials" not in after["verification"]


def test_a_source_that_is_not_a_sha256_never_names_a_file(root, tmp_path):
    """`source_sha256` is joined into a path; a value that is not a sha256 is refused before that."""
    secret = tmp_path / "outside.json"
    secret.write_text(json.dumps({"final_url": "https://example.test/should-not-be-read"}), encoding="utf-8")
    climbing = {"type": "cv", "quote": "Upload a current CV.", "source_sha256": f"../{secret.stem}"}
    stored = checked([climbing], root)["materials"]["items"][0]
    assert stored["check"] == "source_sha256 is not a sha256" and "source_url" not in stored


def test_dropping_failing_entries_counts_them_so_the_page_is_not_read_as_empty(root):
    bad = {"type": "cv", "quote": "not on the page"}
    data = drop_failing(verify(school_file([bad], rejected=0), root))
    block = data["programs"][0]["materials"]
    assert block["items"] == [] and block["rejected"] == 1
    assert materials.extracted(data["programs"][0]) is False


# ---------------------------------------------------------------------------------------------------
# Extracted, or not
# ---------------------------------------------------------------------------------------------------


def test_not_extracted_is_not_the_same_as_nothing_asked():
    no_block = {"snapshot_sha256": SHA}
    read_and_empty = {"materials": {"items": [], "rejected": 0}}
    only_refusals = {"materials": {"items": [], "rejected": 2}}
    failed = {"materials": {"items": [{**CV, "check": "quote not found in snapshot"}]}}
    withdrawn = {"materials": {"items": [], "rejected": 0, "withdrawn": "the page was a cookie wall"}}
    assert materials.extracted(no_block) is False
    assert materials.extracted(read_and_empty) is True and materials.accepted_items(read_and_empty) == []
    assert materials.extracted(only_refusals) is False
    assert materials.extracted(failed) is False
    assert materials.extracted(withdrawn) is False
    assert materials.extracted({"materials": {}}) is False, "a block without an items list was never a reading"
    # Only a block takes a position; a file without one says nothing about materials.
    assert [materials.says_not_extracted(p) for p in (no_block, read_and_empty, only_refusals, withdrawn)] == [
        False, False, True, True]


def test_entries_that_would_read_alike_are_told_apart():
    names = materials.display_names([
        ("recommendation", 2, None, "Two references."),
        ("other", None, "passport copy", "A copy of your passport."),
        ("other", None, "course descriptions", "Describe each core course."),
        ("personal_statement", None, None, "Describe your goals in 500 words."),
        ("personal_statement", None, "why this school", "Tell us why you chose us."),
    ])
    assert names == ["推荐信 2 封", "passport copy", "course descriptions",
                     "个人陈述（Describe your goals in 500 words.）", "个人陈述（why this school）"]
    assert len(set(names)) == len(names)


def test_keys_number_further_entries_of_one_type():
    items = [{"type": "recommendation"}, {"type": "other"}, {"type": "other"}, {"type": "cv"}, {"type": "other"}]
    assert materials.keys_for(items) == ["recommendation", "other", "other-2", "cv", "other-3"]


def test_a_digest_moves_with_the_requirement_and_not_with_its_spacing():
    base = materials.digest("recommendation", 2, None, "Two letters are required.")
    assert materials.digest("recommendation", 2, None, "Two  letters are\nrequired.") == base
    assert materials.digest("recommendation", 3, None, "Two letters are required.") != base
    assert materials.digest("recommendation", 2, "academic", "Two letters are required.") != base


def test_labels_give_the_count_with_its_measure_word():
    assert materials.label("recommendation", 2) == "推荐信 2 封"
    assert materials.label("personal_statement", 1) == "个人陈述 1 篇"
    assert materials.label("transcript", 2) == "成绩单 2 份"
    assert materials.label("cv") == "简历"


# ---------------------------------------------------------------------------------------------------
# The import and the catalogue
# ---------------------------------------------------------------------------------------------------


PID = program_id_for(KEY, {"url": URL, "name": NAME})


@pytest.fixture
def cleanup(db_session):
    yield
    db_session.rollback()
    db_session.execute(delete(ProgramPrerequisite).where(ProgramPrerequisite.program_id == PID))
    db_session.execute(delete(ProgramMaterial).where(ProgramMaterial.program_id == PID))
    db_session.execute(delete(Program).where(Program.id == PID))
    db_session.execute(delete(SourceVersion).where(SourceVersion.source_id == source_id_for(URL)))
    db_session.execute(delete(Source).where(Source.id == source_id_for(URL)))
    db_session.execute(delete(University).where(University.id == KEY))
    db_session.commit()


def stored(session):
    session.expire_all()
    return [(row.key, row.type, row.count, row.note, row.quote, row.source_url) for row in session.scalars(
        select(ProgramMaterial).where(ProgramMaterial.program_id == PID).order_by(ProgramMaterial.sort_order))]


def served() -> dict:
    return TestClient(app).get("/api/programs", params={"ids": PID}).json()[0]


def test_passed_entries_are_imported_with_their_quote_and_page(db_session, require_db, cleanup, root):
    portfolio = {"type": "portfolio", "count": 3, "source_sha256": LINKED_SHA,
                 "quote": "Applicants to design programmes submit a portfolio of 3 projects."}
    bad = {"type": "writing_sample", "quote": "not on the page"}
    import_school(db_session, verify(school_file([RECOMMENDATION, bad, CV, portfolio]), root), SCHOOLS, root=root)

    assert stored(db_session) == [
        ("recommendation", "recommendation", 2, "at least one academic referee", RECOMMENDATION["quote"], URL),
        ("cv", "cv", None, None, CV["quote"], URL),
        ("portfolio", "portfolio", 3, None, portfolio["quote"], LINKED_URL),
    ]
    assert db_session.get(Program, PID).materials_snapshot_sha256 == SHA
    wire = served()["materials"]
    assert [item["key"] for item in wire["items"]] == ["recommendation", "cv", "portfolio"]
    assert wire["items"][0] == {"key": "recommendation", "type": "recommendation", "count": 2,
                                "note": "at least one academic referee", "quote": RECOMMENDATION["quote"], "sourceUrl": URL}
    # A machine-checked quote, like everything the importer writes: no person verified the page.
    assert db_session.get(Source, source_id_for(URL)).verified_at is None


def test_a_program_nobody_read_for_materials_serves_null_not_an_empty_list(db_session, require_db, cleanup, root):
    import_school(db_session, verify(school_file(block=False), root), SCHOOLS, root=root)
    assert db_session.get(Program, PID).materials_snapshot_sha256 is None
    assert served()["materials"] is None


def test_a_page_read_and_found_to_list_none_serves_an_empty_list(db_session, require_db, cleanup, root):
    import_school(db_session, verify(school_file([]), root), SCHOOLS, root=root)
    assert db_session.get(Program, PID).materials_snapshot_sha256 == SHA
    assert served()["materials"] == {"items": []}


def test_a_block_of_refusals_only_stays_not_extracted(db_session, require_db, cleanup, root):
    bad = {"type": "cv", "quote": "not on the page"}
    import_school(db_session, verify(school_file([bad]), root), SCHOOLS, root=root)
    assert served()["materials"] is None and stored(db_session) == []


def test_a_file_without_a_block_does_not_blank_materials_already_imported(db_session, require_db, cleanup, root):
    """The queue collects a page again and exports the program without a block; a later import of that
    file must not remove what the material pass wrote."""
    import_school(db_session, verify(school_file([CV]), root), SCHOOLS, root=root)
    import_school(db_session, verify(school_file(block=False), root), SCHOOLS, root=root)
    assert [row[0] for row in stored(db_session)] == ["cv"]
    assert db_session.get(Program, PID).materials_snapshot_sha256 == SHA


def _writes_of(run) -> list[str]:
    writes = []

    def record(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            writes.append(statement.split("(")[0][:80])

    event.listen(engine, "after_cursor_execute", record)
    try:
        run()
    finally:
        event.remove(engine, "after_cursor_execute", record)
    return writes


def test_importing_the_same_materials_again_writes_nothing(db_session, require_db, cleanup, root):
    data = verify(school_file([RECOMMENDATION, CV]), root)
    import_school(db_session, data, SCHOOLS, root=root)
    before = stored(db_session)

    assert _writes_of(lambda: import_school(db_session, verify(school_file([RECOMMENDATION, CV]), root), SCHOOLS, root=root)) == []
    assert _writes_of(lambda: import_materials(db_session, verify(school_file([RECOMMENDATION, CV]), root), SCHOOLS)) == []
    assert stored(db_session) == before


def test_a_changed_list_replaces_the_stored_one(db_session, require_db, cleanup, root):
    import_school(db_session, verify(school_file([RECOMMENDATION, CV]), root), SCHOOLS, root=root)
    import_school(db_session, verify(school_file([CV, STATEMENT]), root), SCHOOLS, root=root)
    assert [row[0] for row in stored(db_session)] == ["cv", "personal_statement"]


def test_the_materials_only_import_touches_nothing_else(db_session, require_db, cleanup, root):
    import_school(db_session, verify(school_file(block=False), root), SCHOOLS, root=root)
    program = db_session.get(Program, PID)
    before = (program.academic_requirement, program.data_status, program.source_id,
              db_session.scalars(select(SourceVersion.id).where(SourceVersion.source_id == source_id_for(URL))).all())

    # The file's other values differ from the catalogue's: a materials-only import must not carry them.
    changed = school_file([CV], fields={"academic": {"text": "another summary", "quote": "A 2:1 honours degree in a numerate subject."}})
    writes = _writes_of(lambda: print(import_materials(db_session, verify(changed, root), SCHOOLS)))

    assert sorted({w.split()[0] + " " + w.split()[1 if w.startswith("UPDATE") else 2] for w in writes}) == [
        "INSERT program_materials", "UPDATE programs"], writes
    db_session.expire_all()
    program = db_session.get(Program, PID)
    assert (program.academic_requirement, program.data_status, program.source_id,
            db_session.scalars(select(SourceVersion.id).where(SourceVersion.source_id == source_id_for(URL))).all()) == before
    assert [row[0] for row in stored(db_session)] == ["cv"]


def test_a_withdrawn_reading_leaves_the_catalogue(db_session, require_db, cleanup, root):
    """A page handed in as "lists none" turned out to be a cookie wall: taken back in the file, it must
    not stay in the catalogue as a statement about the program."""
    import_school(db_session, verify(school_file([]), root), SCHOOLS, root=root)
    assert served()["materials"] == {"items": []}

    withdrawn = school_file([])
    withdrawn["programs"][0]["materials"]["withdrawn"] = "the snapshot is a cookie wall"
    report = import_materials(db_session, verify(withdrawn, root), SCHOOLS)

    assert report["materials_withdrawn"] == 1
    db_session.expire_all()
    assert db_session.get(Program, PID).materials_snapshot_sha256 is None and served()["materials"] is None
    # Again: nothing left to take back, nothing written.
    assert _writes_of(lambda: import_materials(db_session, verify(withdrawn, root), SCHOOLS)) == []


def test_a_reading_replaced_by_refusals_only_leaves_the_catalogue_too(db_session, require_db, cleanup, root):
    import_school(db_session, verify(school_file([RECOMMENDATION, CV]), root), SCHOOLS, root=root)
    bad = {"type": "cv", "quote": "not on the page at all"}
    import_school(db_session, verify(school_file([bad]), root), SCHOOLS, root=root)
    assert stored(db_session) == [] and served()["materials"] is None


def test_the_materials_only_import_reports_programs_the_catalogue_does_not_hold(db_session, require_db, cleanup, root):
    report = import_materials(db_session, verify(school_file([CV]), root), SCHOOLS)
    assert report["not_in_catalogue"] == 1 and report["materials_written"] == 0
    assert db_session.get(Program, PID) is None, "a materials-only import never creates a program"
