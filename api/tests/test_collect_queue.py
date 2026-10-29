"""The collection queue (openspec/changes/collect-queue): politeness, retries, dedupe, change records,
the budget, export and discovery. No network and no model: fetch and extract are stand-ins that write
snapshot files the way the real snapshot tool does."""

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import redis
from sqlalchemy import delete, select

from app.collect import queue
from app.collect import snapshot as snap
from app.collect.changes import diff_fields
from app.collect.discover import candidates, discover_school, listing_links, page_heading, site_of
from app.collect.extract import ExtractResult
from app.collect.ratelimit import HostBucket, RetryLater
from app.collect.text import html_to_text
from app.config import settings
from app.models.collect import CollectPage, PageState, RequirementChange

pytestmark = pytest.mark.usefixtures("require_db")

PAGE = ("<html><body><h1>Master of Data Science</h1><p>Overall IELTS 6.5 with no band below 6.0.</p>"
        + "<p>" + "Course overview and structure. " * 60 + "</p></body></html>")


@pytest.fixture
def client():
    c = redis.Redis.from_url(settings.redis_url)
    yield c
    c.close()


@pytest.fixture
def school(db_session, tmp_path):
    """A school with a `_schools.json`, a data dir and a snapshot root of its own, removed afterwards."""
    key = f"test-queue-{uuid.uuid4().hex[:8]}"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "_schools.json").write_text(json.dumps([{
        "school_key": key, "name_en": "Example University", "name_zh": "示例大学", "country": "Australia",
        "listing_urls": ["https://www.example.edu.au/study/masters"],
    }]))
    root = tmp_path / "snapshots"
    yield {"key": key, "data_dir": data_dir, "root": root}
    db_session.rollback()
    db_session.execute(delete(RequirementChange).where(RequirementChange.school_key == key))
    db_session.execute(delete(CollectPage).where(CollectPage.school_key == key))
    db_session.commit()


def fake_fetch(html_by_url, calls=None):
    """A snapshot tool that serves `html_by_url[url]` (or raises it, when it is an exception)."""

    def fetch(url, school_key, render=False, root=None):
        if calls is not None:
            calls.append(url)
        html = html_by_url[url]
        if isinstance(html, Exception):
            raise html
        return snap.save_snapshot(school_key, url, url, 200, "text/html", html, root, rendered=render)

    return fetch


def ielts(overall, quote="Overall IELTS 6.5 with no band below 6.0.", check="ok"):
    return {"overall": overall, "min_band": 6.0, "quote": quote, "check": check}


def fake_extract(fields, calls=None, usage=None, error=None):
    def extract(school_key, sha, *, program_name, school_name, country, url, root):
        if calls is not None:
            calls.append(sha)
        program = {"name": program_name, "url": url, "snapshot_sha256": sha, "fields": fields,
                   "status": "机器核对" if fields else "待人工"}
        return ExtractResult(program=program, model="deepseek-flash",
                             usage=usage or {"input_tokens": 5000, "output_tokens": 300, "cache_read_tokens": 0},
                             error=error)

    return extract


def budget(client, cap=100.0):
    return queue.Budget(client, f"test-{uuid.uuid4().hex[:6]}", cap)


def add_page(session, school, url="https://www.example.edu.au/mds", **kw):
    page = queue.upsert_page(session, school["key"], url, kw.pop("name", "Master of Data Science"), **kw)
    page.state = PageState.QUEUED
    session.commit()
    return page


def run(session, school, page, **kw):
    kw.setdefault("budget", None)
    return queue.collect_page(session, page.id, root=school["root"], data_dir=school["data_dir"], **kw)


# --- Politeness ---------------------------------------------------------------------------------------


def test_two_workers_take_turns_on_one_host(client):
    """Two buckets on one Redis are two worker processes: the second has to wait for the interval."""
    first = HostBucket(client, settings.limits_key_prefix, interval=0.5)
    second = HostBucket(redis.Redis.from_url(settings.redis_url), settings.limits_key_prefix, interval=0.5)
    assert first.try_take("www.example.edu") == 0
    wait = second.try_take("example.edu")  # www.x and x are one site
    assert 0 < wait <= 0.5
    assert second.try_take("other.example.edu") == 0


def test_a_turn_far_away_frees_the_worker(client):
    slept = []
    bucket = HostBucket(client, settings.limits_key_prefix, interval=30, max_wait=10, sleep=slept.append)
    bucket("slow.example.edu")
    with pytest.raises(RetryLater) as later:
        bucket("slow.example.edu")
    assert later.value.delay > 10 and not slept


def test_a_near_turn_is_waited_for(client):
    slept = []
    bucket = HostBucket(client, settings.limits_key_prefix, interval=0.3, max_wait=10,
                        sleep=lambda s: slept.append(s) or __import__("time").sleep(s))
    bucket("near.example.edu")
    bucket("near.example.edu")
    assert len(slept) == 1 and 0 < slept[0] <= 0.3


def test_the_snapshot_tool_waits_on_the_installed_limiter(tmp_path):
    seen = []
    with snap.use_limiter(seen.append):
        snap.wait_for_turn("www.example.edu", tmp_path)
    assert seen == ["www.example.edu"]
    assert not (tmp_path / "_rate").exists()


def test_a_refusal_expires_after_thirty_days_but_an_untimed_one_holds(tmp_path):
    then = datetime(2026, 10, 1, tzinfo=UTC)
    snap.block_host("www.timed.example.edu", "HTTP 403", tmp_path, now=then)
    assert snap.blocked_host("timed.example.edu", tmp_path, now=then + timedelta(days=29)) == "HTTP 403"
    assert snap.blocked_host("timed.example.edu", tmp_path, now=then + timedelta(days=31)) is None
    hosts = json.loads((tmp_path / "_blocked_hosts.json").read_text())
    hosts["old.example.edu"] = "HTTP 429"  # recorded before refusals carried a time
    (tmp_path / "_blocked_hosts.json").write_text(json.dumps(hosts))
    assert snap.blocked_host("old.example.edu", tmp_path, now=then + timedelta(days=400)) == "HTTP 429"


def test_an_expired_refusal_is_replaced_when_the_host_refuses_again(tmp_path):
    then = datetime(2026, 1, 1, tzinfo=UTC)
    snap.block_host("again.example.edu", "HTTP 403", tmp_path, now=then)
    later = then + timedelta(days=40)
    snap.block_host("again.example.edu", "HTTP 429", tmp_path, now=later)
    assert snap.blocked_host("again.example.edu", tmp_path, now=later + timedelta(days=1)) == "HTTP 429"


# --- One page ----------------------------------------------------------------------------------------


def test_a_refused_page_is_blocked_and_never_extracted(db_session, school, client):
    page = add_page(db_session, school)
    extracted = []
    state = run(db_session, school, page, budget=budget(client),
                fetch=fake_fetch({page.url: snap.Blocked("HTTP 403 for x")}), extract=fake_extract({}, extracted))
    assert state == PageState.BLOCKED and not extracted
    assert "403" in db_session.get(CollectPage, page.id).last_error


@pytest.mark.parametrize("error", [snap.HttpError(503, "x"), TimeoutError("timed out"), ConnectionResetError()])
def test_a_transient_failure_is_raised_for_a_retry(db_session, school, client, error):
    page = add_page(db_session, school)
    with pytest.raises(queue.Transient):
        run(db_session, school, page, budget=budget(client), fetch=fake_fetch({page.url: error}),
            extract=fake_extract({}))
    assert db_session.get(CollectPage, page.id).state == PageState.QUEUED


def test_a_robots_txt_that_did_not_answer_is_retried_not_blocked(db_session, school, client):
    page = add_page(db_session, school)
    error = snap.Blocked("robots.txt disallows (robots.txt itself: no answer (TimeoutError: timed out)): x")
    with pytest.raises(queue.Transient):
        run(db_session, school, page, budget=budget(client), fetch=fake_fetch({page.url: error}), extract=fake_extract({}))
    assert db_session.get(CollectPage, page.id).state == PageState.QUEUED


def test_a_page_deferred_for_money_after_its_fetch_is_due_again_soon(db_session, school, client):
    page = add_page(db_session, school)
    spent = budget(client, cap=0.01)

    def fetch_then_spend(url, school_key, render=False, root=None):
        spent.add(1.0)  # another worker spends the rest while this page is being fetched
        return fake_fetch({url: PAGE})(url, school_key, render, root)

    state = run(db_session, school, page, budget=spent, fetch=fetch_then_spend, extract=fake_extract({}))
    assert state == PageState.DEFERRED and db_session.get(CollectPage, page.id).fetched_at is None


def test_a_later_unchanged_fetch_still_exports_the_last_result(db_session, school, client):
    page = add_page(db_session, school)
    fetch = fake_fetch({page.url: PAGE})
    run(db_session, school, page, budget=budget(client), fetch=fetch, extract=fake_extract({"ielts": ielts(6.5)}))
    page.state = PageState.QUEUED
    db_session.commit()
    assert run(db_session, school, page, budget=budget(client), fetch=fetch, extract=fake_extract({})) == PageState.UNCHANGED
    assert queue.export_school(db_session, school["key"], data_dir=school["data_dir"])["added"] == 1


def test_concurrent_refusals_are_all_kept(tmp_path):
    import threading

    threads = [threading.Thread(target=snap.block_host, args=(f"h{i}.example.edu", "HTTP 403", tmp_path)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(json.loads((tmp_path / "_blocked_hosts.json").read_text())) == 20


def test_a_missing_page_fails_without_a_retry(db_session, school, client):
    page = add_page(db_session, school)
    state = run(db_session, school, page, budget=budget(client), fetch=fake_fetch({page.url: snap.HttpError(404, "x")}),
                extract=fake_extract({}))
    assert state == PageState.FAILED


def test_the_same_snapshot_costs_no_model_call(db_session, school, client):
    page = add_page(db_session, school)
    extracted = []
    fetch = fake_fetch({page.url: PAGE})
    assert run(db_session, school, page, budget=budget(client), fetch=fetch,
               extract=fake_extract({"ielts": ielts(6.5)}, extracted)) == PageState.DONE
    page.state = PageState.QUEUED
    db_session.commit()
    assert run(db_session, school, page, budget=budget(client), fetch=fetch,
               extract=fake_extract({"ielts": ielts(7.0)}, extracted)) == PageState.UNCHANGED
    assert len(extracted) == 1
    assert db_session.scalar(select(RequirementChange).where(RequirementChange.page_id == page.id)) is None


def test_the_same_visible_text_in_different_html_costs_no_model_call(db_session, school, client):
    page = add_page(db_session, school)
    extracted = []
    run(db_session, school, page, budget=budget(client), fetch=fake_fetch({page.url: PAGE}),
        extract=fake_extract({"ielts": ielts(6.5)}, extracted))
    page.state = PageState.QUEUED
    db_session.commit()
    noisy = PAGE.replace("<body>", '<body><script>var csrf="a1b2"</script>')
    assert run(db_session, school, page, budget=budget(client), fetch=fake_fetch({page.url: noisy}),
               extract=fake_extract({}, extracted)) == PageState.UNCHANGED
    assert len(extracted) == 1


def test_a_changed_requirement_is_recorded_against_the_committed_file(db_session, school, client):
    """The first re-collection of a committed page compares with the file (D6)."""
    url = "https://www.example.edu.au/mds"
    (school["data_dir"] / f"{school['key']}.json").write_text(json.dumps({
        "school_key": school["key"], "school_name_en": "Example University", "programs": [
            {"name": "Master of Data Science", "url": url, "snapshot_sha256": "a" * 64, "status": "机器核对",
             "fields": {"ielts": ielts(6.5)}}]}))
    page = add_page(db_session, school, url=url)
    new_page = PAGE.replace("6.5", "7.0")
    state = run(db_session, school, page, budget=budget(client), fetch=fake_fetch({url: new_page}),
                extract=fake_extract({"ielts": ielts(7.0, quote="Overall IELTS 7.0 with no band below 6.0.")}))
    assert state == PageState.DONE
    change = db_session.scalars(select(RequirementChange).where(RequirementChange.page_id == page.id)).one()
    assert (change.field, change.kind) == ("ielts", "changed")
    assert change.old_value["overall"] == 6.5 and change.new_value["overall"] == 7.0
    assert change.old_sha256 == "a" * 64 and change.new_sha256 == hashlib.sha256(new_page.encode()).hexdigest()
    assert "check" not in change.new_value


def test_a_first_collection_is_not_a_change(db_session, school, client):
    page = add_page(db_session, school)
    run(db_session, school, page, budget=budget(client), fetch=fake_fetch({page.url: PAGE}),
        extract=fake_extract({"ielts": ielts(6.5)}))
    assert db_session.scalar(select(RequirementChange).where(RequirementChange.page_id == page.id)) is None


def test_a_page_that_lost_every_value_records_no_removals(db_session, school, client):
    page = add_page(db_session, school)
    run(db_session, school, page, budget=budget(client), fetch=fake_fetch({page.url: PAGE}),
        extract=fake_extract({"ielts": ielts(6.5)}))
    page.state = PageState.QUEUED
    db_session.commit()
    state = run(db_session, school, page, budget=budget(client),
                fetch=fake_fetch({page.url: "<html><body>Checking your browser…</body></html>"}),
                extract=fake_extract({}))
    assert state == PageState.NEEDS_HUMAN
    assert db_session.scalar(select(RequirementChange).where(RequirementChange.page_id == page.id)) is None
    assert db_session.get(CollectPage, page.id).result["fields"]["ielts"]["overall"] == 6.5


def test_an_unusable_answer_keeps_the_last_result(db_session, school, client):
    page = add_page(db_session, school)
    run(db_session, school, page, budget=budget(client), fetch=fake_fetch({page.url: PAGE}),
        extract=fake_extract({"ielts": ielts(6.5)}))
    page.state = PageState.QUEUED
    db_session.commit()
    state = run(db_session, school, page, budget=budget(client), fetch=fake_fetch({page.url: PAGE.replace("</p>", " Updated.</p>")}),
                extract=fake_extract({}, error="no usable answer"))
    assert state == PageState.NEEDS_HUMAN
    assert db_session.get(CollectPage, page.id).result["fields"]["ielts"]["overall"] == 6.5


def test_the_budget_stops_model_calls(db_session, school, client):
    page = add_page(db_session, school)
    spent = budget(client, cap=0.01)
    extracted = []
    first = run(db_session, school, page, budget=spent, fetch=fake_fetch({page.url: PAGE}),
                extract=fake_extract({"ielts": ielts(6.5)}, extracted, usage={"input_tokens": 10_000, "output_tokens": 0}))
    assert first == PageState.DONE and spent.spent() == pytest.approx(0.02)
    assert db_session.get(CollectPage, page.id).cost_cny == Decimal("0.0200")
    other = add_page(db_session, school, url="https://www.example.edu.au/mit", name="Master of IT")
    state = run(db_session, school, other, budget=spent, fetch=fake_fetch({other.url: PAGE}),
                extract=fake_extract({}, extracted))
    assert state == PageState.DEFERRED and len(extracted) == 1


def test_a_page_that_needs_a_renderer_waits_for_one(db_session, school, client):
    page = add_page(db_session, school, render=True)
    fetched = []
    state = run(db_session, school, page, budget=budget(client), fetch=fake_fetch({page.url: PAGE}, fetched),
                extract=fake_extract({}), can_render=False)
    assert state == PageState.DEFERRED and not fetched


def test_a_thin_page_is_rendered_once_and_from_then_on(db_session, school, client):
    page = add_page(db_session, school)
    calls = []

    def fetch(url, school_key, render=False, root=None):
        calls.append(render)
        html = PAGE if render else "<html><body><div id=app></div>Loading</body></html>"
        return snap.save_snapshot(school_key, url, url, 200, "text/html", html, root, rendered=render)

    state = run(db_session, school, page, budget=budget(client), fetch=fetch, extract=fake_extract({"ielts": ielts(6.5)}))
    assert state == PageState.DONE and calls == [False, True]
    assert db_session.get(CollectPage, page.id).render is True


def test_a_thin_page_on_a_host_without_chrome_costs_no_model_call(db_session, school, client):
    page = add_page(db_session, school)
    extracted = []
    state = run(db_session, school, page, budget=budget(client), can_render=False,
                fetch=fake_fetch({page.url: "<html><body>Loading</body></html>"}), extract=fake_extract({}, extracted))
    assert state == PageState.DEFERRED and not extracted
    assert db_session.get(CollectPage, page.id).render is True


def test_a_discovered_page_with_a_vague_link_is_named_by_its_heading(db_session, school, client):
    page = add_page(db_session, school, name="Learn more")
    run(db_session, school, page, budget=budget(client), fetch=fake_fetch({page.url: PAGE}),
        extract=fake_extract({"ielts": ielts(6.5)}))
    assert db_session.get(CollectPage, page.id).program_name == "Master of Data Science"


# --- Retries in the worker -----------------------------------------------------------------------------


def test_the_worker_retries_a_transient_failure_then_gives_up(db_session, school, monkeypatch):
    from app import worker

    page = add_page(db_session, school)
    calls = []

    def failing(session, page_id, **kw):
        calls.append(page_id)
        raise queue.Transient("timed out")

    monkeypatch.setattr(queue, "collect_page", failing)
    worker.page_task.apply(args=(page.id, "test-retry", 1.0))
    assert len(calls) == queue.MAX_RETRIES + 1
    db_session.expire_all()
    assert db_session.get(CollectPage, page.id).state == PageState.FAILED


def test_the_worker_does_not_retry_a_refusal(db_session, school, monkeypatch):
    from app import worker

    page = add_page(db_session, school)
    calls = []

    def refused(session, page_id, **kw):
        calls.append(page_id)
        return queue._settle(session, session.get(CollectPage, page_id), PageState.BLOCKED, "HTTP 429")

    monkeypatch.setattr(queue, "collect_page", refused)
    worker.page_task.apply(args=(page.id, "test-retry", 1.0))
    assert len(calls) == 1


def test_backoff_grows_and_is_capped():
    delays = [queue.backoff_delay(n, rand=lambda: 1.0) for n in range(8)]
    assert delays[:4] == [60, 120, 240, 480] and max(delays) == 3600
    assert queue.backoff_delay(0, rand=lambda: 0.0) == 30


# --- What counts as a change ------------------------------------------------------------------------------


def test_a_reworded_summary_is_not_a_change():
    old = {"academic": {"text": "A bachelor's degree", "quote": "A Bachelor degree", "check": "ok"}}
    new = {"academic": {"text": "Bachelor's in any field", "quote": "A  bachelor degree", "check": "ok"}}
    assert diff_fields(old, new) == []


def test_a_shorter_quote_of_the_same_sentence_is_not_a_change():
    sentence = "Admission requires (i) a bachelor degree in a cognate discipline; OR (ii) an honours degree."
    old = {"academic": {"text": "x", "quote": sentence, "check": "ok"}}
    new = {"academic": {"text": "y", "quote": "(i) a bachelor degree in a cognate discipline; OR", "check": "ok"}}
    assert diff_fields(old, new, new_text=sentence.lower()) == []
    assert diff_fields(old, new) == []  # without the page, the quotes contain each other


def test_words_the_page_no_longer_states_are_a_change():
    old = {"academic": {"text": "x", "quote": "A credit average (65%)", "check": "ok"}}
    new = {"academic": {"text": "y", "quote": "A distinction average (75%)", "check": "ok"}}
    assert diff_fields(old, new, new_text="a distinction average (75%)")[0]["kind"] == "changed"


def test_a_value_the_model_missed_this_time_is_not_removed():
    old = {"prerequisites": [{"text": "maths", "quote": "Calculus is required", "check": "ok"}],
           "ielts": ielts(6.5)}
    page = "overall ielts 6.5 with no band below 6.0. calculus is required"
    assert diff_fields(old, {}, new_text=page) == []
    assert [c["field"] for c in diff_fields(old, {}, new_text="nothing")] == ["ielts", "prerequisites"]


def test_unchecked_values_are_not_compared():
    assert diff_fields({"ielts": ielts(6.5, check="quote not found")}, {"ielts": ielts(7.0)})[0]["kind"] == "added"


def test_deadlines_are_compared_by_date():
    d = lambda when, label="R1": {"label": label, "date": when, "quote": f"closes {when}", "check": "ok"}  # noqa: E731
    changes = diff_fields({"deadlines": [d("2026-11-30"), d("2027-01-15")]},
                          {"deadlines": [d("2026-11-30", "Round one"), d("2027-02-01")]})
    assert sorted((c["kind"], (c["new"] or c["old"])["date"]) for c in changes) == [("added", "2027-02-01"), ("removed", "2027-01-15")]


def test_a_recommended_score_becoming_a_minimum_is_a_change():
    old = {"ielts": {**ielts(6.5), "recommended": True}}
    assert diff_fields(old, {"ielts": ielts(6.5)})[0]["kind"] == "changed"


# --- Export --------------------------------------------------------------------------------------------


def test_export_replaces_by_url_and_keeps_the_rest(db_session, school, client):
    path = school["data_dir"] / f"{school['key']}.json"
    kept = {"name": "Master of Law", "url": "https://www.example.edu.au/llm", "snapshot_sha256": "c" * 64,
            "status": "机器核对", "fields": {"ielts": ielts(7.0)}}
    path.write_text(json.dumps({"school_key": school["key"], "school_name_en": "Example University",
                                "collector": "claude-code-subagent", "programs": [
        {"name": "Master of Data Science", "url": "https://www.example.edu.au/mds", "snapshot_sha256": "a" * 64,
         "status": "机器核对", "fields": {"ielts": ielts(6.5)}}, kept]}))
    page = add_page(db_session, school)
    run(db_session, school, page, budget=budget(client), fetch=fake_fetch({page.url: PAGE}),
        extract=fake_extract({"ielts": ielts(6.5)}))
    new = add_page(db_session, school, url="https://www.example.edu.au/mit", name="Master of IT")
    run(db_session, school, new, budget=budget(client), fetch=fake_fetch({new.url: PAGE.replace("Data Science", "IT")}),
        extract=fake_extract({}))
    report = queue.export_school(db_session, school["key"], data_dir=school["data_dir"])
    assert report == {"school": school["key"], "replaced": 1, "added": 1, "programs": 3}
    data = json.loads(path.read_text())
    assert data["programs"][1] == kept and data["collector"] == "claude-code-subagent"
    assert data["programs"][0]["snapshot_sha256"] == hashlib.sha256(PAGE.encode()).hexdigest()
    assert data["programs"][0]["fetched_at"]
    assert data["programs"][2]["status"] == "待人工"
    assert "verified_at" not in path.read_text()


def test_export_starts_a_file_for_a_new_school(db_session, school, client):
    page = add_page(db_session, school)
    run(db_session, school, page, budget=budget(client), fetch=fake_fetch({page.url: PAGE}),
        extract=fake_extract({"ielts": ielts(6.5)}))
    queue.export_school(db_session, school["key"], data_dir=school["data_dir"])
    data = json.loads((school["data_dir"] / f"{school['key']}.json").read_text())
    assert data["school_name_en"] == "Example University" and data["country"] == "Australia"
    assert data["verification"] == {"programs": 1, "机器核对": 1, "待人工": 0}


# --- Discovery -----------------------------------------------------------------------------------------

LISTING = """<html><body><nav><a href="/">Home</a><a href="https://twitter.com/x">Twitter</a></nav>
<a href="/courses/master-of-data-science">Master of Data Science</a>
<a href="https://study.example.edu.au/courses/master-of-it#fees">Master of Information Technology</a>
<a href="/courses/bachelor-of-arts">Bachelor of Arts</a>
<a href="/brochure.pdf">Brochure</a><a href="mailto:a@example.edu.au">Email</a>
<a href="/courses/master-of-data-science">Master of Data Science</a></body></html>"""


def test_listing_links_stay_on_the_school_site():
    links = listing_links(LISTING, "https://www.example.edu.au/study/masters")
    assert [link["url"] for link in links] == [
        "https://www.example.edu.au/",
        "https://www.example.edu.au/courses/master-of-data-science",
        "https://study.example.edu.au/courses/master-of-it",
        "https://www.example.edu.au/courses/bachelor-of-arts",
    ]
    assert site_of("handbook.unimelb.edu.au") == "unimelb.edu.au" and site_of("www.ethz.ch") == "ethz.ch"


def test_a_long_listing_shows_only_links_that_look_like_degrees():
    links = [{"url": f"https://x.edu/n{i}", "text": f"News {i}"} for i in range(500)]
    links.append({"url": "https://x.edu/msc", "text": "MSc Physics"})
    assert candidates(links) == [{"url": "https://x.edu/msc", "text": "MSc Physics"}]


def test_discovery_adds_only_the_links_the_page_has(db_session, school, client):
    listing = "https://www.example.edu.au/study/masters"

    def pick(links, info):
        # The model answers with numbers; one is out of range and one repeats.
        numbers = [2, 3, 2, 99]
        return [links[n - 1] for n in numbers if 1 <= n <= len(links)][:2], {"input_tokens": 1000}

    report = discover_school(db_session, school["key"], budget=budget(client), fetch=fake_fetch({listing: LISTING}),
                             pick=pick, data_dir=school["data_dir"], root=school["root"], can_render=False, cap=60)
    pages = db_session.scalars(select(CollectPage).where(CollectPage.school_key == school["key"])).all()
    assert sorted(p.url for p in pages) == ["https://study.example.edu.au/courses/master-of-it",
                                            "https://www.example.edu.au/courses/master-of-data-science"]
    assert all(p.state == PageState.PENDING and p.origin == "discovered" for p in pages)
    assert report["added"] == 2 and report["cost_cny"] == pytest.approx(0.002)


def test_discovery_stops_at_the_cap(db_session, school, client):
    listing = "https://www.example.edu.au/study/masters"
    report = discover_school(db_session, school["key"], budget=budget(client), fetch=fake_fetch({listing: LISTING}),
                             pick=lambda links, info: (links, {}), data_dir=school["data_dir"], root=school["root"],
                             can_render=False, cap=1)
    assert report["added"] == 1


def test_the_model_can_only_choose_numbers_from_the_list():
    from langchain_core.messages import AIMessage

    from app.collect.discover import ProgramLinks, pick_programs

    class Model:
        def with_structured_output(self, schema, method, include_raw):
            class Runner:
                def invoke(self, prompt):
                    return {"raw": AIMessage(content=""), "parsed": ProgramLinks.model_validate(
                        {"picks": [{"number": 2}, {"number": 0}, {"number": 7}, {"number": 2}]})}
            return Runner()

    links = [{"url": "https://x.edu/a", "text": "A"}, {"url": "https://x.edu/b", "text": "MSc B"}]
    picked, _ = pick_programs(links, {"name": "X"}, model=Model())
    assert picked == [links[1]]


def test_page_heading_is_the_first_h1():
    assert page_heading("<h1> </h1><h1>Master of <b>Public Health</b></h1>") == "Master of Public Health"
    assert page_heading("<p>no heading</p>") is None


def test_seed_from_files_adds_committed_programs_once(db_session, school):
    (school["data_dir"] / f"{school['key']}.json").write_text(json.dumps({
        "school_key": school["key"], "school_name_en": "Example University", "collected_at": "2026-10-01",
        "programs": [{"name": "Master of Data Science", "url": "https://www.example.edu.au/mds",
                      "snapshot_sha256": "a" * 64, "fields": {}}]}))
    assert queue.seed_from_files(db_session, school["data_dir"]) == 1
    assert queue.seed_from_files(db_session, school["data_dir"]) == 0
    page = db_session.get(CollectPage, queue.page_id_for(school["key"], "https://www.example.edu.au/mds"))
    assert page.state == PageState.UNCHANGED and page.origin == "file"
    due = queue.due_pages(db_session, datetime(2026, 11, 15, tzinfo=UTC), 10_000)
    assert page.id in {p.id for p in due}
    assert page.id not in {p.id for p in queue.due_pages(db_session, datetime(2026, 10, 20, tzinfo=UTC), 10_000)}


def test_the_cleanup_beat_does_nothing_in_anonymous_mode(monkeypatch):
    from app import worker

    monkeypatch.setattr(settings, "auth_enabled", False)
    assert "skipped" in worker.cleanup.apply().get()


def test_snapshot_text_is_what_dedupe_hashes(tmp_path):
    meta = snap.save_snapshot("s", "https://x.edu/a", "https://x.edu/a", 200, "text/html", PAGE, tmp_path)
    assert queue._snapshot_text_sha("s", meta["sha256"], tmp_path) == queue.text_sha(html_to_text(PAGE))


def test_a_non_ascii_address_is_sent_percent_encoded():
    assert snap.as_uri("https://www.upf.edu/web/máster/ciència?x=á b") == \
        "https://www.upf.edu/web/m%C3%A1ster/ci%C3%A8ncia?x=%C3%A1%20b"
    assert snap.as_uri("https://x.edu/a%20b/c?q=1&r=2") == "https://x.edu/a%20b/c?q=1&r=2"
