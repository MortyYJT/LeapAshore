"""The collection pipeline's own guarantees: text extraction, the verbatim check, politeness."""

import json

import pytest

from app.collect import snapshot as snap
from app.collect.text import html_to_text, normalize
from app.collect.verify import MACHINE_CHECKED, NEEDS_HUMAN, SchemaError, verify

SHA = "a" * 64
OTHER_SHA = "b" * 64
PAGE = """<html><head><title>x</title><style>.a{}</style><script>var s='IELTS 9.0';</script></head>
<body><h1>Master of Data Science</h1>
<p>Applicants need an overall IELTS score of 6.5 with no band below&nbsp;6.0.</p>
<p>Students from China require a weighted average of 80% from a 211 university.</p>
<ul><li>Round 1 closes 30 November 2026</li><li>Prerequisite: linear algebra</li></ul></body></html>"""


def write_snapshot(root, school, sha, html):
    folder = root / school
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{sha}.txt").write_text(html_to_text(html), encoding="utf-8")


def program(fields, sha=SHA):
    return {"name": "Master of Data Science", "url": "https://example.edu/mds", "snapshot_sha256": sha, "fields": fields}


def data(*programs):
    return {"school_key": "example", "school_name_en": "Example University", "programs": list(programs)}


def test_page_text_drops_scripts_and_styles_and_keeps_blocks_apart():
    text = html_to_text(PAGE)
    assert "IELTS 9.0" not in text
    assert ".a{}" not in text
    assert "Master of Data Science\nApplicants need" in text


def test_normalize_folds_spacing_quotes_dashes_and_case():
    assert normalize("No band below “6.0” – ok") == normalize('no band below "6.0" - OK')


def test_a_verbatim_quote_with_matching_numbers_is_machine_checked(tmp_path):
    write_snapshot(tmp_path, "example", SHA, PAGE)
    result = verify(data(program({
        "ielts": {"overall": 6.5, "min_band": 6.0, "quote": "overall IELTS score of 6.5 with no band below 6.0"},
        "china_requirement": {"min_mark_211": 80, "quote": "weighted average of 80% from a 211 university"},
        "deadlines": [{"label": "Round 1", "date": "2026-11-30", "quote": "Round 1 closes 30 November 2026"}],
    })), root=tmp_path)
    assert result["programs"][0]["status"] == MACHINE_CHECKED
    assert result["verification"] == {"programs": 1, MACHINE_CHECKED: 1, NEEDS_HUMAN: 0}


def test_a_paraphrased_quote_goes_to_the_human_queue(tmp_path):
    write_snapshot(tmp_path, "example", SHA, PAGE)
    result = verify(data(program({"ielts": {"overall": 6.5, "quote": "IELTS 6.5 overall, 6.0 in each band"}})), root=tmp_path)
    assert result["programs"][0]["status"] == NEEDS_HUMAN
    assert "quote not found" in result["programs"][0]["fields"]["ielts"]["check"]


def test_a_number_that_is_not_in_its_quote_fails_even_if_the_quote_is_real(tmp_path):
    write_snapshot(tmp_path, "example", SHA, PAGE)
    result = verify(data(program({"ielts": {"overall": 7.0, "quote": "overall IELTS score of 6.5"}})), root=tmp_path)
    assert result["programs"][0]["status"] == NEEDS_HUMAN
    assert "overall=7 not in quote" in result["programs"][0]["fields"]["ielts"]["check"]


def test_a_number_is_not_matched_inside_a_longer_number(tmp_path):
    write_snapshot(tmp_path, "example", SHA, PAGE)
    result = verify(data(program({"china_requirement": {"min_mark_211": 0, "quote": "weighted average of 80%"}})), root=tmp_path)
    assert result["programs"][0]["status"] == NEEDS_HUMAN


def test_a_deadline_whose_day_is_not_quoted_fails(tmp_path):
    write_snapshot(tmp_path, "example", SHA, PAGE)
    result = verify(data(program({"deadlines": [{"label": "R1", "date": "2026-11-29", "quote": "Round 1 closes 30 November 2026"}]})), root=tmp_path)
    assert result["programs"][0]["status"] == NEEDS_HUMAN


def test_a_field_may_cite_another_official_page(tmp_path):
    write_snapshot(tmp_path, "example", SHA, "<p>Course page</p>")
    write_snapshot(tmp_path, "example", OTHER_SHA, PAGE)
    result = verify(data(program({"china_requirement": {"min_mark_211": 80, "source_sha256": OTHER_SHA,
                                                        "quote": "weighted average of 80% from a 211 university"}})), root=tmp_path)
    assert result["programs"][0]["status"] == MACHINE_CHECKED


def test_a_missing_snapshot_never_passes(tmp_path):
    result = verify(data(program({"academic": {"text": "x", "quote": "Master of Data Science"}})), root=tmp_path)
    assert result["programs"][0]["status"] == NEEDS_HUMAN
    assert result["programs"][0]["fields"]["academic"]["check"] == "snapshot missing"


def test_a_program_that_reports_nothing_is_not_machine_checked(tmp_path):
    write_snapshot(tmp_path, "example", SHA, PAGE)
    assert verify(data(program({})), root=tmp_path)["programs"][0]["status"] == NEEDS_HUMAN


@pytest.mark.parametrize("broken, message", [
    ({"school_key": "x", "programs": []}, "school_name_en"),
    (data({"name": "n", "url": "u", "snapshot_sha256": "nothex", "fields": {}}), "sha256"),
    (data(program({"gpa": {"quote": "q"}})), "unknown fields"),
    (data(program({"ielts": {"overall": "6.5", "quote": "q"}})), "must be a number"),
    (data(program({"ielts": {"overall": 6.5, "quote": " "}})), "non-empty quote"),
    (data(program({"deadlines": [{"date": "30 Nov", "quote": "q"}]})), "ISO date"),
])
def test_a_malformed_file_is_refused(broken, message):
    with pytest.raises(SchemaError, match=message):
        verify(broken)


def test_requests_to_one_domain_are_spaced_out(tmp_path):
    clock = {"t": 100.0}
    slept = []

    def sleep(seconds):
        slept.append(seconds)
        clock["t"] += seconds

    snap.wait_for_turn("example.edu", tmp_path, now=lambda: clock["t"], sleep=sleep)
    clock["t"] += 0.5
    snap.wait_for_turn("example.edu", tmp_path, now=lambda: clock["t"], sleep=sleep)
    assert slept == [pytest.approx(snap.MIN_INTERVAL - 0.5)]


def test_a_refused_request_is_recorded_and_not_saved(tmp_path, monkeypatch):
    monkeypatch.setattr(snap, "allowed_by_robots", lambda url: True)
    monkeypatch.setattr(snap, "fetch_html", lambda url: (403, url, "text/html", ""))
    monkeypatch.setattr(snap, "MIN_INTERVAL", 0)
    with pytest.raises(snap.Blocked):
        snap.snapshot("https://example.edu/p", "example", root=tmp_path)
    blocked = json.loads((tmp_path / "example" / "_blocked.json").read_text())
    assert blocked[0]["reason"] == "HTTP 403"
    assert not list((tmp_path / "example").glob("*.html"))


def test_robots_disallow_is_honoured_without_fetching(tmp_path, monkeypatch):
    monkeypatch.setattr(snap, "allowed_by_robots", lambda url: False)
    monkeypatch.setattr(snap, "fetch_html", lambda url: pytest.fail("fetched a disallowed page"))
    with pytest.raises(snap.Blocked):
        snap.snapshot("https://example.edu/private", "example", root=tmp_path)


def test_a_saved_snapshot_is_named_by_the_hash_of_its_html(tmp_path, monkeypatch):
    monkeypatch.setattr(snap, "allowed_by_robots", lambda url: True)
    monkeypatch.setattr(snap, "fetch_html", lambda url: (200, url, "text/html", PAGE))
    monkeypatch.setattr(snap, "MIN_INTERVAL", 0)
    meta = snap.snapshot("https://example.edu/mds", "example", root=tmp_path)
    assert (tmp_path / "example" / f"{meta['sha256']}.txt").read_text().startswith("Master of Data Science")
    assert meta["fetched_at"]
