"""Reading a program's study area from its name, checked against the CRICOS fields that are known."""

import pytest

from app.collect.fields import study_area_from_name
from app.seed_catalog import load_courses, study_area

# Measured on 2026-10-29 when the rules were written: 78.5%. The floor sits just under it, so a rule
# change that files many courses differently from CRICOS fails here instead of passing unnoticed.
CRICOS_AGREEMENT_FLOOR = 0.78


def test_the_rules_agree_with_cricos_on_most_australian_courses():
    pairs = [(c["name"], study_area(c["field"], c["narrow"])) for c in load_courses()]
    known = [(name, area) for name, area in pairs if area]

    agree = sum(study_area_from_name(name) == area for name, area in known)

    assert agree / len(known) >= CRICOS_AGREEMENT_FLOOR


@pytest.mark.parametrize(
    ("name", "area"),
    [
        ("Master of Laws (LLM) in International Business Law", "法律与犯罪学"),
        # "intelligence" and "security" must not pull these away from computing.
        ("Master of Artificial Intelligence", "计算机与数据"),
        ("Master of Cyber Security", "计算机与数据"),
        ("Master of Software Engineering", "计算机与数据"),
        ("MSc Mechanical Engineering", "工程"),
        ("Master of Biomedical Engineering", "工程"),
        ("Master of Public Health", "医学与健康"),
        ("Master of Health Management", "商科与金融"),
        ("Master of Interpreting and Translation", "人文与语言"),
        ("Master of International Relations", "教育与社会科学"),
        ("Accounting and Finance (MSc)", "商科与金融"),
    ],
)
def test_specific_phrases_win_over_general_ones(name, area):
    assert study_area_from_name(name) == area


@pytest.mark.parametrize("name", [None, "", "Master of Advanced Studies"])
def test_a_name_no_rule_matches_stays_unclassified(name):
    assert study_area_from_name(name) is None
