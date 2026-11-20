"""What the applicant said, read without a model.

The advisor may write a date into an application only when the applicant stated it. The model's word
for that is not taken: the tool reads the applicant's own messages and looks for the date there. These
tests pin what counts as a stated date and what does not.
"""

from datetime import date

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agent import stated

TODAY = date(2026, 11, 20)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("截止日期是 2027-01-15", date(2027, 1, 15)),
        ("截止 2027/1/5，别记错", date(2027, 1, 5)),
        ("2027.01.15 截止", date(2027, 1, 15)),
        ("2027年1月15日截止", date(2027, 1, 15)),
        ("２０２７年１月１５日", date(2027, 1, 15)),
        ("截止是 1 月 15 号", date(2027, 1, 15)),
        ("12月1日截止", date(2026, 12, 1)),
        ("今天是 11月20日 截止", date(2026, 11, 20)),
        ("明年3月1日", date(2027, 3, 1)),
        ("今年12月31日", date(2026, 12, 31)),
        ("后年1月5日", date(2028, 1, 5)),
        ("十二月十五日截止", date(2026, 12, 15)),
        ("一月三十一号", date(2027, 1, 31)),
        ("deadline is January 15, 2027", date(2027, 1, 15)),
        ("due Dec 1", date(2026, 12, 1)),
        ("15 Jan 2027", date(2027, 1, 15)),
        ("Feb. 3rd, 2027", date(2027, 2, 3)),
    ],
)
def test_a_written_date_is_read_as_that_date(text, expected):
    assert stated.dates_in([text], TODAY) == {expected}


def test_a_date_without_a_year_is_its_next_occurrence_only():
    # 11 月 19 日 has passed this year, so it can only mean next year's.
    assert stated.dates_in(["11月19日"], TODAY) == {date(2027, 11, 19)}
    assert stated.dates_in(["11月21日"], TODAY) == {date(2026, 11, 21)}


def test_a_date_with_a_year_is_not_also_read_without_it():
    assert stated.dates_in(["2028年1月15日"], TODAY) == {date(2028, 1, 15)}
    assert stated.dates_in(["January 15, 2028"], TODAY) == {date(2028, 1, 15)}


@pytest.mark.parametrize(
    "text",
    [
        "一月中旬吧",
        "下周五截止",
        "月底之前",
        "均分 3.15，雅思 7.5",
        "1/15 截止",  # day/month or month/day: not read
        "2027 年春季入学",
        "2月30日",  # no such day
        "13月1日",
        "大概还有 15 天",
        "Round 2",
        "",
    ],
)
def test_what_is_not_a_written_date_gives_none(text):
    assert stated.dates_in([text], TODAY) == set()


def test_several_messages_give_every_date_in_them():
    found = stated.dates_in(["一轮是 12月1日", "二轮 2027-01-10，三轮 2027年2月1日"], TODAY)
    assert found == {date(2026, 12, 1), date(2027, 1, 10), date(2027, 2, 1)}


def test_only_the_applicant_s_messages_count():
    """A date the model wrote, or a tool returned, is not one the applicant stated."""
    state = {
        "messages": [
            HumanMessage(content="帮我把港大的截止日期记一下", additional_kwargs={"said_on": "2026-11-20"}),
            AIMessage(content="港大的截止日期是 2027-01-15 吗？"),
            ToolMessage(content='[{"deadline": "2027-03-01"}]', tool_call_id="c1"),
            HumanMessage(content="不对，是 2027-02-01"),
        ]
    }
    texts = stated.applicant_texts(state)
    assert texts == [("帮我把港大的截止日期记一下", TODAY), ("不对，是 2027-02-01", None)]
    assert stated.dates_in(texts) == {date(2027, 2, 1)}


def test_applicant_texts_survive_a_missing_or_odd_state():
    assert stated.applicant_texts(None) == []
    assert stated.applicant_texts({}) == []
    assert stated.applicant_texts({"messages": [HumanMessage(content=[{"type": "text", "text": "x"}])]}) == []
    assert stated.applicant_texts({"messages": [HumanMessage(content="x", additional_kwargs={"said_on": "soon"})]}) == [("x", None)]


def test_a_date_without_a_year_is_counted_from_the_day_it_was_said():
    """The conversation is kept for months; "1 月 5 日" said in December is the coming January's, whenever
    it is read. A message with no known day has no year to give."""
    said_in_december = [("截止是 1 月 5 日", date(2026, 12, 20))]
    assert stated.dates_in(said_in_december) == {date(2027, 1, 5)}
    assert stated.dates_in([("截止是 1 月 5 日", None)]) == set()
    assert stated.dates_in([("due Jan 5", None)]) == set()
    assert stated.dates_in([("截止是 2027-01-05", None)]) == {date(2027, 1, 5)}


@pytest.mark.parametrize(
    "text, expected",
    [
        # The month comes first where both orders could be read.
        ("Round 2 Jan 15", {date(2027, 1, 15)}),
        ("Phase 3 Mar 31", {date(2027, 3, 31)}),
        ("IELTS 7 Dec 12", {date(2026, 12, 12)}),
        ("Round 2 Jan 2027 intake", set()),
        ("I may 5 times retake it", set()),
        ("march 3 programs", set()),
        # A year that is not part of the date leaves the date without one.
        ("28年1月15日", set()),
        ("1月15日（2028年）", set()),
        ("2028 年秋季入学，截止 1 月 15 日", set()),
        ("去年12月1日我毕业了", set()),
        ("Jan 15, 28", set()),
        ("Jan 15 '28", set()),
        # ...and one that is part of it is taken.
        ("2028年的1月15日", {date(2028, 1, 15)}),
        ("明年的3月1日", {date(2027, 3, 1)}),
        # A date inside a link is the link's.
        ("见 https://example.edu/news/2027/01/15/deadline 这一页", set()),
    ],
)
def test_a_date_is_not_read_where_the_reading_could_be_wrong(text, expected):
    assert stated.dates_in([text], TODAY) == expected


@pytest.mark.parametrize(
    "phrase, text, expected",
    [
        ("Round 2", "我申的是 round 2", True),
        ("第二轮", "港大我报第二轮", True),
        ("第二轮", "港大我报二轮", False),  # the applicant's own words, not a tidied version
        ("Fall 2027", "fall  2027 入学", True),
        ("", "随便", False),
        ("   ", "随便", False),
        ("推荐信已拿到两封", "记一下：推荐信已拿到两封。", True),
        ("推荐信需要三封", "记一下：推荐信已拿到两封。", False),
        # Whole words: these messages never named a round.
        ("Round 1", "I'm looking at around 12 programs", False),
        ("Round 3", "background 3 years", False),
        ("Round 2", "ground 2 floors", False),
        ("Round 2", "我报Round2，谢谢", True),
        ("R2", "我报 R2", True),
        ("R2", "我报 R20", False),
    ],
)
def test_a_phrase_counts_only_when_the_applicant_wrote_it(phrase, text, expected):
    assert stated.said([text], phrase) is expected
