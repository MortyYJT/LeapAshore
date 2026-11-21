"""The material extraction scorer, on hand-made pages.

`tests/fixtures/materials/` holds a made-up school with five made-up pages, a made-up "extraction" of
them and made-up labels. The numbers asserted on it are arithmetic on that fixture and say nothing
about any extractor.

The last tests are about the two real scores in the repository, both against labels written by a
model: 11 chosen programs (`evals/materials_gold.json`, `evals/results/materials-2026-11-21.json`) and
30 programs drawn at random (`evals/materials_gold_sample.json`,
`evals/results/materials-sample-2026-11-21.json`).
"""

import json
from datetime import date
from pathlib import Path

from evals.materials import check_set, main, metrics, replay, rows_of, score, template

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "materials"
GOLD = FIXTURES / "gold.json"
DATA = FIXTURES / "requirements"
ROOT = FIXTURES / "snapshots"

API = Path(__file__).resolve().parents[1]
REAL_GOLD = API / "evals" / "materials_gold.json"
REAL_DATA = API / "data" / "requirements"
RECORDED = API / "evals" / "results" / "materials-2026-11-21.json"
SAMPLE_GOLD = API / "evals" / "materials_gold_sample.json"
SAMPLE_DRAW = API / "evals" / "materials_sample_2026-11-21.json"
SAMPLE_RECORDED = API / "evals" / "results" / "materials-sample-2026-11-21.json"


def gold() -> dict:
    return json.loads(GOLD.read_text(encoding="utf-8"))


def by_name(rows: list[dict]) -> dict[str, dict]:
    return {row["program_id"].split("-msc-fixture-")[1].rsplit("-", 1)[0]: row for row in rows}


def test_the_fixture_set_is_well_formed_and_its_quotes_are_on_its_pages():
    problems, counts = check_set(gold(), ROOT)
    assert problems == []
    assert counts == {"programs": 5, "labels": 7, "quotes_checked": 7, "quotes_not_checked": 0}


def test_without_the_snapshot_store_the_shape_is_still_checked(tmp_path):
    problems, counts = check_set(gold(), tmp_path)
    assert problems == [] and counts["quotes_checked"] == 0 and counts["quotes_not_checked"] == 7


def test_a_label_is_held_to_the_extraction_s_own_rules():
    data = gold()
    data["programs"][0]["materials"][0]["count"] = 3            # the page says two
    data["programs"][1]["materials"][0]["quote"] = "Three references."  # not on the page
    data["programs"][2]["materials"] = None                     # not labelled
    data["programs"][3]["materials"][0]["type"] = "essay"       # not a type
    data["programs"].append(dict(data["programs"][4]))          # listed twice
    data["labeller"] = ""
    problems, _ = check_set(data, ROOT)
    text = "\n".join(problems)
    assert "count=3 not in quote" in text and "quote not found in snapshot" in text
    assert "is not labelled" in text and "is not one of" in text and "listed twice" in text and "labeller is empty" in text


def test_a_program_is_scored_only_against_an_extraction_of_the_snapshot_that_was_labelled():
    rows = by_name(rows_of(gold(), DATA))
    assert {name: row["state"] for name, row in rows.items()} == {
        "alpha": "scored", "beta": "scored", "gamma": "scored", "delta": "not_extracted", "epsilon": "snapshot_differs"}
    assert rows["alpha"]["gold"] == [["cv", None], ["personal_statement", None], ["recommendation", 2], ["transcript", None]]
    assert rows["alpha"]["predicted"] == [["cv", None], ["personal_statement", None], ["portfolio", None], ["recommendation", 2]]
    # What was not scored brings nothing to the comparison, in either direction.
    assert rows["delta"]["predicted"] == [] and rows["epsilon"]["predicted"] == []


def test_the_metrics_of_the_fixture_are_its_arithmetic():
    result = metrics(rows_of(gold(), DATA))
    assert result["programs"] == {"scored": 3, "not_extracted": 1, "snapshot_differs": 1, "not_on_file": 0}
    # Alpha: three of four labelled types found, plus a portfolio the page says is not required.
    # Beta: the one labelled type found. Gamma: nothing labelled, nothing extracted.
    assert result["pairs"] == {"gold": 5, "predicted": 5, "both": 4}
    assert (result["precision"], result["recall"]) == (0.8, 0.8)
    # Counts are compared where either side states one: Alpha's letters agree, Beta's do not.
    assert result["count_agreement"] == {"pairs": 2, "agree": 1, "rate": 0.5}
    assert result["empty_pages"] == {"labelled_empty": 1, "extracted_empty_too": 1}
    assert result["by_type"]["transcript"] == {"gold": 1, "predicted": 0, "both": 0, "precision": None, "recall": 0.0}
    assert result["by_type"]["portfolio"] == {"gold": 0, "predicted": 1, "both": 0, "precision": 0.0, "recall": None}
    assert "writing_sample" not in result["by_type"], "a type only an unscored program has is not counted"


def test_a_rate_over_nothing_is_none_not_zero():
    result = metrics([{"program_id": "x", "state": "not_extracted", "gold": [["cv", None]], "predicted": []}])
    assert result["precision"] is None and result["recall"] is None and result["count_agreement"]["rate"] is None


def test_two_entries_of_one_type_are_compared_together():
    def row(predicted):
        return [{"program_id": "x", "state": "scored", "gold": [["recommendation", 2], ["recommendation", 1]],
                 "predicted": predicted}]

    same = metrics(row([["recommendation", 1], ["recommendation", 2]]))
    fewer = metrics(row([["recommendation", 2]]))
    assert same["pairs"]["both"] == 1 and same["count_agreement"] == {"pairs": 1, "agree": 1, "rate": 1.0}
    assert fewer["count_agreement"] == {"pairs": 1, "agree": 0, "rate": 0.0}


def test_an_entry_read_from_another_page_is_not_compared_with_the_labels_of_this_one(tmp_path):
    """A label says what one page asks for. An entry that cites a linked page (`source_sha256`, rule 6
    of the brief) is beyond what the labeller read: it is left out of the comparison and counted."""
    data = json.loads((DATA / "fixture-school.json").read_text(encoding="utf-8"))
    gamma = next(program for program in data["programs"] if program["name"] == "MSc Fixture Gamma")
    gamma["materials"]["items"] = [
        {"type": "recommendation", "count": 2, "quote": "Two letters of recommendation are required.",
         "source_sha256": "a" * 64, "source_url": "https://fixture.example/how-to-apply", "check": "ok"},
        # Citing the block's own snapshot is the same as citing nothing: it is this page's entry.
        {"type": "cv", "quote": "Upload a current CV.", "source_sha256": gamma["snapshot_sha256"], "check": "ok"},
    ]
    (tmp_path / "fixture-school.json").write_text(json.dumps(data), encoding="utf-8")

    row = by_name(rows_of(gold(), tmp_path))["gamma"]
    assert row["state"] == "scored" and row["gold"] == [] and row["predicted"] == [["cv", None]]
    result = score(gold(), tmp_path, today=date(2026, 11, 21), set_name="gold.json")
    assert result["entries_from_other_pages"] == {row["program_id"]: 1}
    assert score(gold(), DATA, today=date(2026, 11, 21))["entries_from_other_pages"] == {}


def test_a_recorded_score_replays_to_the_same_metrics_and_a_changed_one_does_not(tmp_path):
    recorded = tmp_path / "score.json"
    recorded.write_text(json.dumps(score(gold(), DATA, today=date(2026, 11, 20), set_name="gold.json")), encoding="utf-8")
    again, same = replay(recorded)
    assert same and again["pairs"]["both"] == 4

    data = json.loads(recorded.read_text(encoding="utf-8"))
    data["metrics"]["recall"] = 1.0
    recorded.write_text(json.dumps(data), encoding="utf-8")
    assert replay(recorded)[1] is False


def test_a_template_names_the_page_and_carries_no_extractor_output():
    ids = [program["program_id"] for program in gold()["programs"]][:2]
    blank = template(DATA, ids)
    assert [program["program_id"] for program in blank["programs"]] == ids
    assert all(program["materials"] is None for program in blank["programs"])
    assert "Two letters" not in json.dumps(blank) and blank["labeller"] is None
    problems, _ = check_set(blank, ROOT)
    assert sum("is not labelled" in problem for problem in problems) == 2


def test_the_command_line(tmp_path, capsys):
    common = ["--set", str(GOLD), "--data-dir", str(DATA), "--root", str(ROOT)]
    assert main(["--check", *common]) == 0
    assert json.loads(capsys.readouterr().out)["problems"] == []

    out = tmp_path / "score.json"
    assert main(["--score", *common, "--out", str(out)]) == 0
    capsys.readouterr()
    assert main(["--replay", str(out)]) == 0
    assert json.loads(capsys.readouterr().out)["matches_recorded"] is True

    assert main(["--check", "--set", str(tmp_path / "absent.json")]) == 2
    assert "nothing has been labelled yet" in capsys.readouterr().out

    broken = tmp_path / "broken.json"
    data = gold()
    data["programs"][0]["materials"] = None
    broken.write_text(json.dumps(data), encoding="utf-8")
    assert main(["--score", "--set", str(broken), "--data-dir", str(DATA), "--root", str(ROOT)]) == 1, "an unlabelled set is not scored"


def test_the_first_recorded_score_replays_and_is_the_score_of_the_committed_files():
    """The first real score: 11 programs that were chosen (the signed-out demo's), labelled by a model.

    Its metrics follow from its own rows, and its rows are what the committed labels and requirement
    files give today, so the figures in `docs/measurements.md` cannot drift from the data. It is a
    pilot check of the pipeline and says nothing about the rest of the catalogue. An extraction or a
    label that changes needs a new score file, and this test then names the new one.
    """
    again, same = replay(RECORDED)
    assert same, "the recorded metrics are not the metrics of the recorded rows"
    recorded = json.loads(RECORDED.read_text(encoding="utf-8"))
    labelled = json.loads(REAL_GOLD.read_text(encoding="utf-8"))

    # No snapshot store in CI: the shape of every label is still checked, the quotes are not.
    problems, counts = check_set(labelled, None)
    assert problems == []
    assert (counts["programs"], counts["labels"], counts["quotes_checked"]) == (11, 40, 0)
    # The set says what labelled it: a model, not a person.
    assert "not a person" in labelled["labeller"] and recorded["labeller"] == labelled["labeller"]

    elsewhere: dict[str, int] = {}
    assert rows_of(labelled, REAL_DATA, elsewhere) == recorded["rows"], "the files or the labels changed since the score was recorded"
    # After the score was recorded, one block gained an entry read from a page its program page links
    # to (Imperial's application-process page: two referees). The label for that program is `[]` and
    # was written from the program page alone, so the entry is not compared with it and the recorded
    # row stands: the page that was labelled still lists no document.
    assert elsewhere == {"imperial-college-london-msc-computing-f38aa7": 1}
    assert again["programs"] == {"scored": 11, "not_extracted": 0, "snapshot_differs": 0, "not_on_file": 0}
    assert again["pairs"] == {"gold": 32, "predicted": 32, "both": 32}
    assert again["count_agreement"] == {"pairs": 4, "agree": 4, "rate": 1.0}
    assert again["empty_pages"] == {"labelled_empty": 4, "extracted_empty_too": 4}
    # Entries, which the pair unit hides: 40 labels against 41 entries. The one without a label is a
    # sentence both readers left out and a later review added to the extraction; the labels were not
    # changed, so the set is known to lack it.
    assert sum(len(row["gold"]) for row in recorded["rows"]) == 40
    assert sum(len(row["predicted"]) for row in recorded["rows"]) == 41
    extra = [row["program_id"] for row in recorded["rows"] if len(row["gold"]) != len(row["predicted"])]
    assert extra == ["university-of-manchester-artificial-intelligence-msc-404945"]


DIFFER = {
    # program: (pairs only the labels have, pairs only the extraction has)
    "korea-university-master-s-program-in-humanities-a-a00e9e": ([["language_score", 1]], [["language_score", None]]),
    "university-of-california-master-of-development-practice-m-817ec2": ([["test_score", None]], []),
    "mcmaster-university-manufacturing-engineering-meng-50cfdf": ([["other", None], ["other", None]], []),
    "queen-s-university-at-ki-master-of-education-on-campus-967b3d": ([], [["personal_statement", None]]),
    "the-education-university-master-of-arts-in-womens-studies-609406": ([["other", None], ["other", None]], []),
}


def test_the_random_sample_score_replays_and_is_the_score_of_the_committed_files():
    """30 programs drawn at random from the catalogue, read by one model and labelled by another.

    The score is recorded as it came out: no entry and no label of these programs was changed to make
    the two agree, and the five programs on which they differ are named here. The labels are a
    model's, the unit is (program, type), and each program is one page; `docs/measurements.md` says
    what the figures can and cannot carry.
    """
    again, same = replay(SAMPLE_RECORDED)
    assert same, "the recorded metrics are not the metrics of the recorded rows"
    recorded = json.loads(SAMPLE_RECORDED.read_text(encoding="utf-8"))
    labelled = json.loads(SAMPLE_GOLD.read_text(encoding="utf-8"))
    drawn = json.loads(SAMPLE_DRAW.read_text(encoding="utf-8"))

    # How the sample was drawn is on file, and the labelled set is that sample, program for program.
    assert (drawn["seed"], drawn["frame"], len(drawn["programs"])) == (20261121, 7540, 30)
    assert "random.Random(seed).sample(frame, 30)" in drawn["rule"]
    assert [program["program_id"] for program in labelled["programs"]] == [program["program_id"] for program in drawn["programs"]]
    chosen = {program["program_id"] for program in json.loads(REAL_GOLD.read_text(encoding="utf-8"))["programs"]}
    assert not chosen & {program["program_id"] for program in drawn["programs"]}, "a sampled program is also one of the chosen 11"

    problems, counts = check_set(labelled, None)
    assert problems == []
    assert (counts["programs"], counts["labels"], counts["quotes_checked"]) == (30, 37, 0)
    assert "not a person" in labelled["labeller"] and recorded["labeller"] == labelled["labeller"]

    elsewhere: dict[str, int] = {}
    assert rows_of(labelled, REAL_DATA, elsewhere) == recorded["rows"], "the files or the labels changed since the score was recorded"
    assert elsewhere == {}
    assert again["programs"] == {"scored": 30, "not_extracted": 0, "snapshot_differs": 0, "not_on_file": 0}
    assert again["pairs"] == {"gold": 33, "predicted": 31, "both": 30}
    assert (again["precision"], again["recall"]) == (0.9677, 0.9091)
    assert again["count_agreement"] == {"pairs": 4, "agree": 3, "rate": 0.75}
    assert again["empty_pages"] == {"labelled_empty": 17, "extracted_empty_too": 17}

    # Coverage, the finding that matters more than the rates: most program pages list no document.
    rows = recorded["rows"]
    assert sum(bool(row["predicted"]) for row in rows) == 12, "pages on which the extraction found any document"
    assert sum(bool(row["gold"]) for row in rows) == 13, "pages on which the labels have any document"
    assert (sum(len(row["gold"]) for row in rows), sum(len(row["predicted"]) for row in rows)) == (37, 33)

    def only(mine: list, theirs: list) -> list:
        left = list(theirs)
        return [pair for pair in mine if pair not in left or left.remove(pair)]

    differ = {row["program_id"]: (only(row["gold"], row["predicted"]), only(row["predicted"], row["gold"]))
              for row in rows if row["gold"] != row["predicted"]}
    assert differ == DIFFER


def test_only_the_scores_this_file_replays_are_recorded():
    """A score file nobody replays could be quoted without being checked."""
    assert sorted(path.name for path in RECORDED.parent.glob("materials-*.json")) == [RECORDED.name, SAMPLE_RECORDED.name]
