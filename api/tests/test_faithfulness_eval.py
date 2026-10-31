"""The summary faithfulness eval's model-free half, run in CI.

`evals/results/faithfulness-2026-10-30.json` is the one live run of the judge (DeepSeek) over the 100
seeded fields and the advisor's 75 recorded sentences of `evals/faithfulness_set.json`, labelled by a
Claude subagent blind to the judge. Replaying it re-reads the recorded function-call arguments with the
production parser, so a change to how verdicts are read that would move the reported numbers fails here.
"""

import json
import random
from pathlib import Path

from evals.faithfulness import (
    SEED,
    SEED_V2,
    SET_V2,
    SIZE,
    breakdown,
    check_labels,
    draw_stratified,
    load_set,
    metrics,
    replay,
    stale_claims,
    weighted,
)

RECORDED = Path(__file__).resolve().parents[1] / "evals" / "results" / "faithfulness-2026-10-30.json"
RECORDED_V2 = Path(__file__).resolve().parents[1] / "evals" / "results" / "faithfulness-2026-10-31.json"


def test_the_recorded_run_replays_to_its_reported_metrics():
    again, same = replay(RECORDED)
    assert same
    fields, sentences = again["fields"], again["sentences"]
    assert (fields["n"], fields["blocked"], fields["caught"], fields["false_blocks"]) == (100, 27, 22, 5)
    assert (sentences["n"], sentences["blocked"], sentences["caught"], sentences["false_blocks"]) == (75, 11, 5, 6)


def test_the_set_is_the_seeded_draw_and_fully_labelled():
    data = load_set()
    assert data["seed"] == SEED and len(data["fields"]) == SIZE
    assert check_labels(data) == []
    # The draw is reproducible from the population size alone.
    picked = sorted(random.Random(SEED).sample(range(data["population"]), SIZE))
    assert len(picked) == len(set(picked)) == SIZE


def test_the_metrics_count_not_checked_as_blocked():
    rows = [{"id": "a", "label": "supported", "verdict": "not checked: x"},
            {"id": "b", "label": "unsupported", "verdict": "unsupported: y"},
            {"id": "c", "label": "supported", "verdict": "ok"}]
    m = metrics(rows)
    assert (m["blocked"], m["false_blocks"], m["caught"], m["not_checked"]) == (2, 1, 1, 1)
    assert m["false_block_rate"] == 0.5 and m["catch_rate"] == 1.0
    json.dumps(m)


def test_only_the_china_fields_were_labelled_on_the_old_claim_wording():
    """The recorded run asked about china_requirement with wording later changed; a new live run must
    relabel exactly those rows first (`run_live` refuses until then)."""
    data = load_set()
    china = sorted(r["id"] for r in data["fields"] if r["field"] == "china_requirement")
    assert stale_claims(data) == china and len(china) == 9


# ---- the second, stratified set (2026-10-31) ---------------------------------------------------------


def _items(field_sizes: dict[str, int]) -> list[dict]:
    return [{"school_key": "s", "program_index": n, "field": name, "item_index": 0}
            for name, size in field_sizes.items() for n in range(size)]


def test_the_stratified_draw_takes_the_same_number_from_every_field_and_skips_the_excluded():
    items = _items({"academic": 50, "toefl": 30, "china_requirement": 4})
    excluded = {("s", 0, "academic", 0), ("s", 1, "toefl", 0)}
    picked = draw_stratified(items, seed=7, per_field=10, exclude=excluded)
    by_field = {}
    for i in picked:
        by_field.setdefault(items[i]["field"], []).append(i)
    # A field with fewer usable items than asked for gives all of them.
    assert {k: len(v) for k, v in by_field.items()} == {"academic": 10, "toefl": 10, "china_requirement": 4}
    assert not {(items[i]["school_key"], items[i]["program_index"], items[i]["field"], items[i]["item_index"])
                for i in picked} & excluded
    assert picked == sorted(picked) == draw_stratified(items, seed=7, per_field=10, exclude=excluded)
    assert picked != draw_stratified(items, seed=8, per_field=10, exclude=excluded)


def test_the_breakdown_scores_each_group_on_its_own():
    rows = [{"id": "a", "field": "toefl", "label": "unsupported", "verdict": "unsupported: x"},
            {"id": "b", "field": "toefl", "label": "supported", "verdict": "ok"},
            {"id": "c", "field": "ielts", "label": "supported", "verdict": "unsupported: y"}]
    out = breakdown(rows, "field")
    assert sorted(out) == ["ielts", "toefl"]
    assert (out["toefl"]["caught"], out["toefl"]["catch_rate"], out["toefl"]["false_blocks"]) == (1, 1.0, 0)
    assert (out["ielts"]["false_blocks"], out["ielts"]["false_block_rate"], out["ielts"]["catch_rate"]) == (1, 1.0, None)


def test_the_weighted_rates_scale_each_field_to_its_share_of_the_population():
    # Field A: 2 sampled of 100 in the population, both unsupported, one caught.
    # Field B: 2 sampled of 900, one unsupported (caught), one supported (wrongly blocked).
    rows = [{"id": "a1", "field": "A", "label": "unsupported", "verdict": "unsupported: x"},
            {"id": "a2", "field": "A", "label": "unsupported", "verdict": "ok"},
            {"id": "b1", "field": "B", "label": "unsupported", "verdict": "unsupported: y"},
            {"id": "b2", "field": "B", "label": "supported", "verdict": "unsupported: z"}]
    w = weighted(rows, {"A": 100, "B": 900})
    # Estimated unsupported: 100 + 450 = 550, caught 50 + 450 = 500; supported 450, wrongly blocked 450;
    # blocked 50 + 900 = 950, of them unsupported 500.
    assert w["unsupported_share"] == round(550 / 1000, 4)
    assert w["catch_rate"] == round(500 / 550, 4)
    assert w["false_block_rate"] == 1.0
    assert w["precision"] == round(500 / 950, 4)
    assert w["block_rate"] == round(950 / 1000, 4)


def test_the_second_set_keeps_the_first_draw_and_relabels_its_china_rows_on_the_current_wording():
    old, new = load_set(), load_set(SET_V2)
    assert check_labels(new) == [] and stale_claims(new) == []
    first = {r["id"]: r for r in new["fields"] if r["sample"] == "random-20261030"}
    assert sorted(first) == sorted(r["id"] for r in old["fields"])
    relabelled = sorted(i for i, r in first.items() if "claim_2026_10_30" in r)
    assert relabelled == stale_claims(old)
    stratified = [r for r in new["fields"] if r["sample"] == f"stratified-{SEED_V2}"]
    sizes = {}
    for r in stratified:
        sizes[r["field"]] = sizes.get(r["field"], 0) + 1
    assert set(sizes.values()) == {new["per_field"]}
    keys = {(r["school_key"], r["program_index"], r["field"], r["item_index"]) for r in new["fields"]}
    assert len(keys) == len(new["fields"])  # no field drawn twice
    assert [r["id"] for r in new["sentences"]] == [r["id"] for r in old["sentences"]]


def test_the_second_run_replays_to_its_reported_metrics():
    """The one live run (DeepSeek, 2026-10-31) over the second set, labelled before it ran."""
    again, same = replay(RECORDED_V2)
    assert same
    fields, sentences = again["fields"], again["sentences"]
    assert (fields["n"], fields["labelled_unsupported"], fields["blocked"], fields["caught"],
            fields["false_blocks"]) == (490, 147, 130, 103, 27)
    first, stratified = again["fields_by_sample"]["random-20261030"], again["fields_by_sample"][f"stratified-{SEED_V2}"]
    assert (first["n"], first["labelled_unsupported"], first["caught"], first["false_blocks"]) == (100, 27, 23, 4)
    assert (stratified["n"], stratified["labelled_unsupported"], stratified["caught"],
            stratified["false_blocks"]) == (390, 120, 80, 23)
    assert (sentences["n"], sentences["blocked"], sentences["caught"], sentences["false_blocks"]) == (75, 9, 5, 4)
    assert again["fields_weighted"]["catch_rate"] == 0.6928
