"""The summary faithfulness eval's model-free half, run in CI.

`evals/results/faithfulness-2026-10-30.json` is the one live run of the judge (DeepSeek) over the 100
seeded fields and the advisor's 75 recorded sentences of `evals/faithfulness_set.json`, labelled by a
Claude subagent blind to the judge. Replaying it re-reads the recorded function-call arguments with the
production parser, so a change to how verdicts are read that would move the reported numbers fails here.
"""

import json
import random
from pathlib import Path

from evals.faithfulness import SEED, SIZE, check_labels, load_set, metrics, replay, stale_claims

RECORDED = Path(__file__).resolve().parents[1] / "evals" / "results" / "faithfulness-2026-10-30.json"


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
