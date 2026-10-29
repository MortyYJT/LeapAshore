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
    monkeypatch.setattr(snap, "allowed_by_robots", lambda url, root=None: True)
    monkeypatch.setattr(snap, "fetch_html", lambda url, **_: (403, url, "text/html", ""))
    monkeypatch.setattr(snap, "MIN_INTERVAL", 0)
    with pytest.raises(snap.Blocked):
        snap.snapshot("https://example.edu/p", "example", root=tmp_path)
    blocked = json.loads((tmp_path / "example" / "_blocked.json").read_text())
    assert blocked[0]["reason"] == "HTTP 403"
    assert not list((tmp_path / "example").glob("*.html"))


def test_robots_disallow_is_honoured_without_fetching(tmp_path, monkeypatch):
    monkeypatch.setattr(snap, "allowed_by_robots", lambda url, root=None: False)
    monkeypatch.setattr(snap, "fetch_html", lambda url, **_: pytest.fail("fetched a disallowed page"))
    with pytest.raises(snap.Blocked):
        snap.snapshot("https://example.edu/private", "example", root=tmp_path)


def test_a_saved_snapshot_is_named_by_the_hash_of_its_html(tmp_path, monkeypatch):
    monkeypatch.setattr(snap, "allowed_by_robots", lambda url, root=None: True)
    monkeypatch.setattr(snap, "fetch_html", lambda url, **_: (200, url, "text/html", PAGE))
    monkeypatch.setattr(snap, "MIN_INTERVAL", 0)
    meta = snap.snapshot("https://example.edu/mds", "example", root=tmp_path)
    assert (tmp_path / "example" / f"{meta['sha256']}.txt").read_text().startswith("Master of Data Science")
    assert meta["fetched_at"]


def test_a_deadline_needs_its_year_and_month_in_the_quote(tmp_path):
    """A year taken from elsewhere on the page ("31 May of the previous year") is an inference."""
    write_snapshot(tmp_path, "example", SHA, "<p>Applications close 31 May of the previous year.</p><p>Round 1 closes 30 November 2026</p><p>Deadline: 2026-12-15</p>")
    result = verify(data(program({"deadlines": [{"label": "S1", "date": "2026-05-31", "quote": "Applications close 31 May of the previous year."}]})), root=tmp_path)
    assert "year 2026 not in quote" in result["programs"][0]["fields"]["deadlines"][0]["check"]
    wrong_month = verify(data(program({"deadlines": [{"label": "R1", "date": "2026-10-30", "quote": "Round 1 closes 30 November 2026"}]})), root=tmp_path)
    assert "month 10 not in quote" in wrong_month["programs"][0]["fields"]["deadlines"][0]["check"]
    numeric = verify(data(program({"deadlines": [{"label": "R2", "date": "2026-12-15", "quote": "Deadline: 2026-12-15"}]})), root=tmp_path)
    assert numeric["programs"][0]["status"] == MACHINE_CHECKED


def test_dropping_failing_values_keeps_the_ones_that_passed(tmp_path):
    from app.collect.verify import drop_failing

    write_snapshot(tmp_path, "example", SHA, PAGE)
    checked = verify(data(program({
        "ielts": {"overall": 6.5, "quote": "overall IELTS score of 6.5"},
        "deadlines": [{"label": "S1", "date": "2026-05-31", "quote": "Round 1 closes 30 November 2026"},
                      {"label": "R1", "date": "2026-11-30", "quote": "Round 1 closes 30 November 2026"}],
        "toefl": {"overall": 90, "quote": "TOEFL 90"},
    })), root=tmp_path)
    cleaned = verify(drop_failing(checked), root=tmp_path)
    fields = cleaned["programs"][0]["fields"]
    assert set(fields) == {"ielts", "deadlines"}
    assert [d["date"] for d in fields["deadlines"]] == ["2026-11-30"]
    assert cleaned["programs"][0]["status"] == MACHINE_CHECKED


def test_a_host_that_refused_once_is_not_asked_again(tmp_path, monkeypatch):
    monkeypatch.setattr(snap, "allowed_by_robots", lambda url, root=None: True)
    monkeypatch.setattr(snap, "MIN_INTERVAL", 0)
    monkeypatch.setattr(snap, "fetch_html", lambda url, **_: (429, url, "text/html", ""))
    with pytest.raises(snap.Blocked):
        snap.snapshot("https://example.edu/a", "example", root=tmp_path)
    monkeypatch.setattr(snap, "fetch_html", lambda url, **_: pytest.fail("asked a host that had refused us"))
    with pytest.raises(snap.Blocked, match="not asking again"):
        snap.snapshot("https://example.edu/b", "example", root=tmp_path)


def test_a_redirect_into_a_disallowed_page_is_not_saved(tmp_path, monkeypatch):
    """robots.txt governs where a request ends up, not only the URL that was asked for."""
    monkeypatch.setattr(snap, "allowed_by_robots", lambda url, root=None: "gradoffice" not in url)
    monkeypatch.setattr(snap, "MIN_INTERVAL", 0)
    monkeypatch.setattr(snap, "fetch_html", lambda url, **_: (200, "https://gradoffice.example.edu/", "text/html", PAGE))
    with pytest.raises(snap.Blocked, match="redirected"):
        snap.snapshot("https://www.example.edu/graduate", "example", root=tmp_path)
    assert not list((tmp_path / "example").glob("*.html"))
    blocked = json.loads((tmp_path / "example" / "_blocked.json").read_text())
    assert "gradoffice.example.edu" in blocked[0]["reason"]


def test_a_plain_fetch_stops_before_following_a_redirect_it_may_not_follow():
    import urllib.request

    handler = snap.CheckedRedirects(lambda url: "robots.txt disallows" if "gradoffice" in url else None)
    request = urllib.request.Request("https://www.example.edu/graduate")
    with pytest.raises(snap.Blocked, match="gradoffice"):
        handler.redirect_request(request, None, 302, "Found", {}, "https://gradoffice.example.edu/")
    assert handler.redirect_request(request, None, 302, "Found", {}, "https://www.example.edu/graduate/") is not None


@pytest.mark.parametrize("code, allowed", [(404, True), (403, False), (429, False), (503, False)])
def test_robots_txt_errors_mean_keep_out_unless_the_file_is_simply_missing(tmp_path, monkeypatch, code, allowed):
    import urllib.error

    def refuse(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, code, "x", {}, None)

    monkeypatch.setattr(snap.urllib.request, "urlopen", refuse)
    monkeypatch.setattr(snap, "MIN_INTERVAL", 0)
    assert snap.allowed_by_robots(f"https://e{code}.example/page", root=tmp_path) is allowed


def test_a_whole_number_does_not_match_inside_a_decimal(tmp_path):
    write_snapshot(tmp_path, "example", SHA, "<p>overall 6.5, no band below 6.5</p>")
    result = verify(data(program({"ielts": {"overall": 6.5, "min_band": 6, "quote": "overall 6.5, no band below 6.5"}})), root=tmp_path)
    assert "min_band=6 not in quote" in result["programs"][0]["fields"]["ielts"]["check"]


def test_a_numeric_date_must_be_the_deadline_itself(tmp_path):
    write_snapshot(tmp_path, "example", SHA, "<p>Deadline: 2026-05-31</p>")
    result = verify(data(program({"deadlines": [{"label": "x", "date": "2026-05-05", "quote": "Deadline: 2026-05-31"}]})), root=tmp_path)
    assert "not the date the quote states" in result["programs"][0]["fields"]["deadlines"][0]["check"]


def test_a_quote_from_another_page_records_that_page(tmp_path):
    write_snapshot(tmp_path, "example", SHA, "<p>Course page</p>")
    write_snapshot(tmp_path, "example", OTHER_SHA, PAGE)
    (tmp_path / "example" / f"{OTHER_SHA}.json").write_text(json.dumps({"final_url": "https://example.edu/china"}))
    result = verify(data(program({"china_requirement": {"min_mark_211": 80, "source_sha256": OTHER_SHA,
                                                        "quote": "weighted average of 80% from a 211 university"}})), root=tmp_path)
    assert result["programs"][0]["fields"]["china_requirement"]["source_url"] == "https://example.edu/china"


def test_every_committed_file_still_matches_its_snapshots():
    """A value edited after `verify --write` would import as machine-checked; re-check what we can.

    Snapshots are not committed, so this runs only on a machine that collected them, and skips the
    programmes whose snapshots are absent rather than calling them failures.
    """
    import copy
    from pathlib import Path

    from app.collect.snapshot import SNAPSHOT_ROOT

    data_dir = Path(__file__).resolve().parents[1] / "data" / "requirements"
    checked = 0
    for path in sorted(p for p in data_dir.glob("*.json") if not p.name.startswith("_")):
        stored = json.loads(path.read_text(encoding="utf-8"))
        if not (SNAPSHOT_ROOT / stored["school_key"]).exists():
            continue
        fresh = verify(copy.deepcopy(stored))
        for before, after in zip(stored["programs"], fresh["programs"]):
            if any(item.get("check") == "snapshot missing" for name, f in after["fields"].items()
                   for item in (f if isinstance(f, list) else [f])):
                continue
            assert before.get("status") == after["status"], f"{path.name}: {before['name']} changed since verify"
            checked += 1
    if not checked:
        pytest.skip("no local snapshots to re-check against")


def test_a_us_page_writes_numeric_dates_month_first(tmp_path):
    """12/01/2026 on a US page is 1 December, not 12 January; reading it the other way round would
    accept a wrong date as machine-checked."""
    write_snapshot(tmp_path, "example", SHA, "<p>Fall 2027 application deadline: 12/01/2026</p>")
    quote = "Fall 2027 application deadline: 12/01/2026"

    def check(country, when):
        result = verify({**data(program({"deadlines": [{"label": "Fall", "date": when, "quote": quote}]})), "country": country}, root=tmp_path)
        return result["programs"][0]["status"]

    assert check("United States", "2026-12-01") == MACHINE_CHECKED
    assert check("United States", "2026-01-12") == NEEDS_HUMAN
    assert check("United Kingdom", "2026-01-12") == MACHINE_CHECKED
    assert check("United Kingdom", "2026-12-01") == NEEDS_HUMAN


def test_a_refusal_from_www_holds_for_the_bare_host_and_back(tmp_path, monkeypatch):
    """www.cs.example.edu and cs.example.edu are one site: switching between them is not a new host."""
    snap.block_host("www.cs.example.edu", "HTTP 403", tmp_path)
    assert snap.blocked_host("cs.example.edu", tmp_path) == "HTTP 403"
    snap.block_host("grad.example.edu", "HTTP 429", tmp_path)
    assert snap.blocked_host("www.grad.example.edu", tmp_path) == "HTTP 429"
    assert snap.blocked_host("other.example.edu", tmp_path) is None


def test_a_numeric_date_in_a_mixed_order_country_must_be_unambiguous(tmp_path):
    """Canadian pages write dates both ways: 03/04/2027 could be 3 April or 4 March, so it proves
    neither; 15/01/2027 can only be 15 January."""
    write_snapshot(tmp_path, "example", SHA, "<p>Deadline A: 03/04/2027</p><p>Deadline B: 15/01/2027</p>")

    def check(when, quote):
        result = verify({**data(program({"deadlines": [{"label": "x", "date": when, "quote": quote}]})), "country": "Canada"}, root=tmp_path)
        return result["programs"][0]["status"]

    assert check("2027-04-03", "Deadline A: 03/04/2027") == NEEDS_HUMAN
    assert check("2027-03-04", "Deadline A: 03/04/2027") == NEEDS_HUMAN
    assert check("2027-01-15", "Deadline B: 15/01/2027") == MACHINE_CHECKED
