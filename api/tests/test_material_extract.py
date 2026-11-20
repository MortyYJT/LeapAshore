"""The material extraction's command line: what to read, the page text, and handing entries in.

The school, its page and its requirements are made up for the test; no real program is described.
"""

import json

import pytest

from app.collect import material_extract as tool
from app.collect import materials
from app.collect.importer import program_id_for
from app.collect.verify import verify

KEY = "test-extract-university"
SHA = "1" * 64
OTHER_SHA = "2" * 64
LINKED_SHA = "3" * 64
URL = "https://example.test/fixture/msc-invented"
PAGE = """FIXTURE PAGE: MSc Invented
Documents
Two letters of recommendation are required.
A personal statement of up to 500 words.
Upload a current CV.
"""
PROGRAM = {"name": "MSc Invented", "url": URL, "snapshot_sha256": SHA,
           "fields": {"prerequisites": [{"text": "none", "quote": "Documents"}]}}
SECOND = {"name": "MSc Also Invented", "url": URL + "-2", "snapshot_sha256": OTHER_SHA, "fields": {}}
PID = program_id_for(KEY, PROGRAM)

GOOD = {"type": "recommendation", "count": 2, "quote": "Two letters of recommendation are required."}
CV = {"type": "cv", "quote": "Upload a current CV."}
WRONG_COUNT = {"type": "recommendation", "count": 3, "quote": "Two letters of recommendation are required."}
INVENTED = {"type": "portfolio", "quote": "A portfolio of five works."}


@pytest.fixture
def store(tmp_path):
    data_dir, root = tmp_path / "requirements", tmp_path / "snapshots"
    (root / KEY).mkdir(parents=True)
    data_dir.mkdir()
    (root / KEY / f"{SHA}.txt").write_text(PAGE, encoding="utf-8")
    (root / KEY / f"{LINKED_SHA}.txt").write_text("FIXTURE PAGE: linked\nSend one writing sample.\n", encoding="utf-8")
    (root / KEY / f"{LINKED_SHA}.json").write_text(json.dumps({"final_url": URL + "/apply"}), encoding="utf-8")
    path = data_dir / f"{KEY}.json"
    path.write_text(json.dumps({"school_key": KEY, "school_name_en": "Test Extract University", "country": "United Kingdom",
                                "programs": [PROGRAM, SECOND]}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return {"data_dir": data_dir, "root": root, "path": path}


def hand_in(store, entries, sha=SHA, **kwargs):
    return tool.accept(store["data_dir"], store["root"], PID, {"snapshot_sha256": sha, "materials": entries}, **kwargs)


def block(store) -> dict | None:
    return json.loads(store["path"].read_text(encoding="utf-8"))["programs"][0].get("materials")


def test_targets_list_each_program_with_the_snapshot_to_read(store):
    rows = tool.targets(store["data_dir"], store["root"], [KEY])
    assert [(r["program_id"], r["snapshot_sha256"], r["snapshot"], r["extracted"]) for r in rows] == [
        (PID, SHA, "ok", False), (program_id_for(KEY, SECOND), OTHER_SHA, "missing", False)]
    assert rows[0]["url"] == URL and rows[0]["chars"] == len(PAGE.encode())


def test_targets_by_id_keep_the_order_asked_and_name_what_is_not_on_file(store):
    rows = tool.targets(store["data_dir"], store["root"], program_ids=["nowhere-000000", PID])
    assert rows[0] == {"program_id": "nowhere-000000", "error": "not in any requirement file"}
    assert rows[1]["program_id"] == PID


def test_pending_leaves_out_what_is_already_extracted(store):
    hand_in(store, [GOOD])
    assert [r["program_id"] for r in tool.targets(store["data_dir"], store["root"], [KEY], pending=True)] == [
        program_id_for(KEY, SECOND)]


def test_text_is_the_stored_page_as_it_is(store):
    header, text = tool.page_text(store["data_dir"], store["root"], PID)
    assert text == PAGE and header["snapshot_sha256"] == SHA and header["view"] == "full"
    assert tool.page_text(store["data_dir"], store["root"], PID, lines=(3, 4))[1] == (
        "Two letters of recommendation are required.\nA personal statement of up to 500 words.")


def test_a_long_page_is_shown_as_the_lines_around_material_words(store):
    filler = "\n".join(f"Filler line {n} about campus life." for n in range(3000))
    (store["root"] / KEY / f"{SHA}.txt").write_text(filler + "\nTwo letters of recommendation are required.\n" + filler, encoding="utf-8")
    header, text = tool.page_text(store["data_dir"], store["root"], PID)
    assert header["view"].startswith("excerpt") and "Two letters of recommendation are required." in text
    assert len(text) < 1000
    assert len(tool.page_text(store["data_dir"], store["root"], PID, full=True)[1]) > tool.EXCERPT_OVER


def test_text_of_a_program_without_its_snapshot_is_refused(store):
    with pytest.raises(tool.Refused, match="snapshot text missing"):
        tool.page_text(store["data_dir"], store["root"], program_id_for(KEY, SECOND))


def test_accepted_entries_are_written_and_refused_ones_reported_with_the_reason(store):
    report = hand_in(store, [GOOD, WRONG_COUNT, INVENTED, CV], extractor="test-reader")

    assert report["accepted"] == 2 and report["written"] is True and report["extracted"] is True
    assert report["rejected"] == [
        {"entry": 1, "type": "recommendation", "reason": "count=3 not in quote"},
        {"entry": 2, "type": "portfolio", "reason": "quote not found in snapshot"},
    ]
    written = block(store)
    assert written["snapshot_sha256"] == SHA and written["extractor"] == "test-reader" and written["rejected"] == 2
    assert written["items"] == [{**GOOD, "check": "ok"}, {**CV, "check": "ok"}]
    # What `accept` wrote is what `verify` finds: the file checks clean against the same store.
    again = verify(json.loads(store["path"].read_text(encoding="utf-8")), store["root"])
    assert [item["check"] for item in again["programs"][0]["materials"]["items"]] == ["ok", "ok"]


def test_a_refused_entry_is_never_repaired(store):
    hand_in(store, [WRONG_COUNT])
    assert block(store)["items"] == [] and block(store)["rejected"] == 1
    assert materials.extracted({"materials": block(store)}) is False


def test_an_empty_list_says_the_page_was_read_and_lists_none(store):
    report = hand_in(store, [])
    assert report["extracted"] is True and report["accepted"] == 0
    assert block(store)["items"] == [] and block(store)["rejected"] == 0


def test_a_submission_about_another_snapshot_is_refused_whole(store):
    with pytest.raises(tool.Refused, match="snapshot_sha256 must be"):
        hand_in(store, [GOOD], sha=OTHER_SHA)
    assert block(store) is None


def test_a_submission_that_is_not_a_list_of_entries_is_refused_whole(store):
    with pytest.raises(tool.Refused):
        tool.accept(store["data_dir"], store["root"], PID, {"snapshot_sha256": SHA, "materials": "CV"})
    with pytest.raises(tool.Refused):
        tool.accept(store["data_dir"], store["root"], PID, [GOOD])
    assert block(store) is None


def test_the_same_entry_twice_is_kept_once(store):
    report = hand_in(store, [GOOD, dict(GOOD)])
    assert report["accepted"] == 1 and report["rejected"][0]["reason"] == "same type and quote as entry 0"


def test_an_entry_from_a_linked_page_cites_that_page(store):
    linked = {"type": "writing_sample", "count": 1, "quote": "Send one writing sample.", "source_sha256": LINKED_SHA}
    assert hand_in(store, [linked])["accepted"] == 1
    assert block(store)["items"][0]["source_url"] == URL + "/apply"


def test_handing_in_the_same_again_does_not_rewrite_the_file(store):
    hand_in(store, [GOOD], today=__import__("datetime").date(2026, 11, 20))
    before = store["path"].read_bytes()
    report = hand_in(store, [GOOD], today=__import__("datetime").date(2026, 11, 25))
    assert report["written"] is False and store["path"].read_bytes() == before


def test_a_dry_run_reports_and_writes_nothing(store):
    before = store["path"].read_bytes()
    report = hand_in(store, [GOOD, INVENTED], dry_run=True)
    assert report["accepted"] == 1 and report["written"] is False and store["path"].read_bytes() == before


def test_writing_keeps_the_rest_of_the_file_byte_for_byte(store):
    original = store["path"].read_bytes()
    hand_in(store, [GOOD])
    after = json.loads(store["path"].read_text(encoding="utf-8"))
    del after["programs"][0]["materials"]
    # Same keys in the same order, same indentation, same final newline.
    assert (json.dumps(after, ensure_ascii=False, indent=1) + "\n").encode() == original
    assert [path.name for path in store["data_dir"].iterdir()] == [store["path"].name], "no lock or temporary file is left"


def test_extractors_working_on_one_school_do_not_overwrite_each_other(store):
    """Twelve programs of one file handed in at once: every block is there afterwards."""
    from concurrent.futures import ThreadPoolExecutor

    data = json.loads(store["path"].read_text(encoding="utf-8"))
    extra = [{"name": f"MSc Invented {n}", "url": f"{URL}-{n}", "snapshot_sha256": SHA, "fields": {}} for n in range(12)]
    data["programs"] += extra
    store["path"].write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    ids = [program_id_for(KEY, program) for program in extra]

    def one(pid):
        return tool.accept(store["data_dir"], store["root"], pid, {"snapshot_sha256": SHA, "materials": [GOOD]}, school=KEY)

    with ThreadPoolExecutor(max_workers=12) as pool:
        reports = list(pool.map(one, ids))

    assert all(report["written"] for report in reports)
    after = {program_id_for(KEY, p): p for p in json.loads(store["path"].read_text(encoding="utf-8"))["programs"]}
    assert all(materials.extracted(after[pid]) for pid in ids)
    assert tool.status(store["data_dir"])["extracted"] == 12


def test_a_withdrawn_reading_is_not_an_extraction(store):
    hand_in(store, [])
    assert tool.targets(store["data_dir"], store["root"], [KEY])[0]["extracted"] is True

    report = tool.withdraw(store["data_dir"], PID, "the snapshot is a cookie wall")

    assert report["extracted"] is False
    assert block(store)["withdrawn"] == "the snapshot is a cookie wall" and block(store)["items"] == []
    assert tool.targets(store["data_dir"], store["root"], [KEY], pending=True)[0]["program_id"] == PID, "it is to be read again"
    assert tool.status(store["data_dir"])["withdrawn"] == 1 and tool.status(store["data_dir"])["extracted"] == 0
    # Handing it in again replaces the withdrawal.
    assert hand_in(store, [GOOD])["extracted"] is True and "withdrawn" not in block(store)


def test_there_is_nothing_to_withdraw_from_a_program_nobody_read(store):
    with pytest.raises(tool.Refused, match="nothing to withdraw"):
        tool.withdraw(store["data_dir"], PID, "no reason")
    with pytest.raises(tool.Refused, match="needs a reason"):
        tool.withdraw(store["data_dir"], PID, "  ")


def test_status_counts_what_the_files_hold(store):
    hand_in(store, [GOOD, CV])
    assert tool.status(store["data_dir"]) == {
        "programs": 2, "extracted": 1, "with_entries": 1, "page_lists_none": 0, "refused_only": 0, "withdrawn": 0,
        "entries": 2, "by_type": {"cv": 1, "recommendation": 1}}


def test_the_command_line_prints_json_and_exits_3_on_a_refusal(store, capsys, tmp_path):
    base = ["--data-dir", str(store["data_dir"]), "--root", str(store["root"])]
    submission = tmp_path / "submission.json"
    submission.write_text(json.dumps({"snapshot_sha256": SHA, "materials": [GOOD]}), encoding="utf-8")

    assert tool.main([*base, "targets", "--school", KEY, "--pending"]) == 0
    assert [json.loads(line)["program_id"] for line in capsys.readouterr().out.splitlines()] == [
        PID, program_id_for(KEY, SECOND)]
    assert tool.main([*base, "text", PID]) == 0
    header, _, body = capsys.readouterr().out.partition("\n-----\n")
    assert json.loads(header)["program_id"] == PID and body == PAGE + "\n"
    assert tool.main([*base, "accept", PID, "--json", str(submission), "--school", KEY]) == 0
    assert json.loads(capsys.readouterr().out)["accepted"] == 1
    assert tool.main([*base, "accept", "nowhere-000000", "--json", str(submission)]) == 3
    assert "refused" in json.loads(capsys.readouterr().out)
