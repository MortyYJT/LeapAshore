"""How the advisor recognises schools and subjects in a question. No database, no model.

The school rows here are the catalogue's real ids and names (as `universities` stores them), so the
curated short forms in `data/advisor/university_aliases.json` apply to them as they do in production.
"""

import json
import re

from app.agent import catalog_match
from app.agent.catalog_match import SchoolIndex, normalize, parse
from app.collect.fields import RULES, study_area_from_name

ROWS = [
    ("imperial-college-london", "帝国理工学院", "Imperial College London"),
    ("university-of-hong-kong", "香港大學", "The University of Hong Kong"),
    ("chinese-university-of-hong-kong", "香港中文大學", "The Chinese University of Hong Kong"),
    ("ucl", "伦敦大学学院", "University College London (UCL)"),
    ("massachusetts-institute-of-technology", "麻省理工学院", "Massachusetts Institute of Technology (MIT)"),
    ("london-school-of-economics-and-political-science", "伦敦政治经济学院",
     "The London School of Economics and Political Science (LSE)"),
    ("usyd", "悉尼大学", "University of Sydney"),
    ("cricos-00917K", "西悉尼大学", "Western Sydney University"),
    ("cricos-00109J", "纽卡斯尔大学（澳大利亚）", "The University of Newcastle, Australia (UON)"),
    ("newcastle-university", "纽卡斯尔大学（英国）", "Newcastle University"),
    ("cricos-00002J", "麦考瑞大学", "Macquarie University (Sydney, Australia)"),
    ("university-of-british-columbia", "不列颠哥伦比亚大学", "University of British Columbia"),
    ("columbia-university", "哥伦比亚大学", "Columbia University"),
]
INDEX = SchoolIndex(ROWS)


def schools(question: str) -> list[str]:
    return parse(INDEX, question).schools


def fields(question: str) -> list[str]:
    return parse(INDEX, question).fields


def test_traditional_and_simplified_fold_to_the_same_text():
    assert normalize("香港大學 數據科學 碩士") == normalize("香港大学 数据科学 硕士")
    assert normalize("ＵＣＬ") == "ucl"  # full-width Latin, as a Chinese keyboard types it


def test_a_short_form_finds_the_school():
    assert schools("帝国理工计算机硕士的语言要求是多少？") == ["imperial-college-london"]
    assert schools("港大的金融硕士要什么条件") == ["university-of-hong-kong"]
    assert schools("港中文 数据科学") == ["chinese-university-of-hong-kong"]


def test_simplified_chinese_finds_a_school_stored_in_traditional():
    assert schools("香港大学计算机科学硕士申请要求") == ["university-of-hong-kong"]
    assert schools("香港中文大学商科") == ["chinese-university-of-hong-kong"]


def test_traditional_chinese_finds_it_too():
    assert schools("香港大學的教育碩士要求") == ["university-of-hong-kong"]


def test_english_names_and_abbreviations_in_parentheses():
    assert schools("UCL computer science master requirements") == ["ucl"]
    assert schools("What are the requirements at the University of Hong Kong?") == ["university-of-hong-kong"]
    assert schools("MIT 计算机硕士要什么条件") == ["massachusetts-institute-of-technology"]
    assert schools("LSE 经济学") == ["london-school-of-economics-and-political-science"]


def test_a_latin_short_form_must_be_a_whole_word():
    assert schools("how do I submit my documents") == []


def test_the_longest_name_wins_where_two_overlap():
    assert schools("西悉尼大学的计算机硕士") == ["cricos-00917K"]
    assert schools("不列颠哥伦比亚大学 商科") == ["university-of-british-columbia"]
    assert schools("哥伦比亚大学 商科") == ["columbia-university"]


def test_one_name_for_two_schools_returns_both():
    assert sorted(schools("纽卡斯尔大学的商科硕士")) == ["cricos-00109J", "newcastle-university"]


def test_a_place_in_parentheses_is_not_a_name():
    assert schools("Sydney, Australia 有哪些学校") == []


def test_two_schools_come_back_in_the_order_asked():
    assert schools("港中文和港大的计算机对比") == ["chinese-university-of-hong-kong", "university-of-hong-kong"]


def test_the_subject_is_a_program_field_area():
    assert fields("帝国理工学院计算机") == ["计算机与数据"]
    assert fields("港大的金融硕士") == ["商科与金融"]
    assert fields("城大电子工程") == ["工程"]


def test_a_longer_subject_beats_a_word_inside_it():
    assert fields("帝国理工 软件工程") == ["计算机与数据"]
    assert fields("帝国理工 生物医学工程") == ["工程"]


def test_words_inside_a_school_name_are_not_a_subject():
    assert fields("伦敦政治经济学院的硕士要求") == []
    assert fields("The London School of Economics and Political Science requirements") == []


def test_a_question_without_a_subject_has_no_field():
    assert fields("帝国理工的语言要求") == []
    assert fields("申请需要什么材料") == []  # 材料 is not 材料科学


def test_a_specific_subject_narrows_and_a_broad_one_only_ranks():
    assert parse(INDEX, "港大 金融").narrowing_pattern
    assert parse(INDEX, "港大 商科").narrowing_pattern is None
    assert parse(INDEX, "港大 商科").name_pattern
    # A broad and a specific subject together do not narrow: the broad one asks for the whole area.
    assert parse(INDEX, "港大 计算机和金融").narrowing_pattern is None


def test_every_subject_area_is_one_the_catalogue_uses():
    areas = {area for _, area in RULES}
    for entry in catalog_match.subject_entries():
        assert entry["field"] in areas, entry


def test_every_subject_gloss_is_filed_under_its_area_by_the_program_classifier():
    """The subject words select `Program.field`, which `app.collect.fields` assigns from program names.
    Each entry's English gloss must land in the same area, or the vocabulary and the catalogue disagree."""
    for entry in catalog_match.subject_entries():
        assert entry["gloss"], entry
        for gloss in entry["gloss"]:
            assert study_area_from_name(gloss) == entry["field"], (gloss, entry["field"])


def test_subject_name_patterns_compile_in_python_and_avoid_the_postgres_incompatible_escape():
    for entry in catalog_match.subject_entries():
        re.compile(entry["name"])
        assert "\\b" not in entry["name"], entry["name"]


def test_no_curated_short_form_names_two_schools():
    seen: dict[str, str] = {}
    for uid, aliases in catalog_match.curated_aliases().items():
        for alias in aliases:
            folded = normalize(alias)
            assert seen.setdefault(folded, uid) == uid, f"{alias!r} names {seen[folded]} and {uid}"


def test_the_alias_file_holds_no_logic_only_names():
    data = json.loads(catalog_match.ALIASES_FILE.read_text(encoding="utf-8"))
    assert set(data) == {"_note", "aliases"}
    assert all(isinstance(v, list) and all(isinstance(a, str) for a in v) for v in data["aliases"].values())
