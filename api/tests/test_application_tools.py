"""The advisor's tools for the applicant's own applications, called the way the graph calls them with
the confirm step stubbed.

Each write tool stops the graph with `interrupt()` and writes only after the applicant answers. Outside
a running graph `interrupt` has nowhere to stop, so these tests replace it with a stub that records the
question and answers the way `routers.advisor` does: yes or no, with the changes and the base the
question carried. The writes are real: they go through `app.services.application_records` to the
development database, and the subjects are swept by `conftest`'s autouse fixture.

The stream, the checkpointer and the confirm endpoint are covered in
`test_advisor_application_tools.py`.
"""

import json
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from sqlalchemy import delete, func, select

from app.agent import application_tools as tools
from app.agent import stated
from app.agent.tools import TOOLS, get_my_applications, propose_portfolio_change
from app.agent import tools as portfolio_tools
from app.db import SessionLocal
from app.deps import load_or_create_profile
from app.models.application import Application
from app.models.application_plan import ApplicationPlan
from app.models.program import Program, ProgramDeadline
from app.seed import seed_programs
from app.seed_catalog import seed_catalog
from app.services import application_records as records
from app.services.application_records import RecordCreate, RecordPatch
from app.services.applications import replace_applications

pytestmark = pytest.mark.usefixtures("require_db")

SOURCE = "https://example.edu/admissions/deadlines"
OTHER_SOURCE = "https://example.edu/another-program/deadlines"


def future(days: int) -> date:
    return datetime.now(UTC).date() + timedelta(days=days)


@pytest.fixture
def catalogue():
    """Two seeded programs. The first gets two collected deadlines, the second one of its own; all
    three are removed afterwards, so the shared catalogue is left as it was found."""
    made: list[str] = []
    with SessionLocal() as s:
        seed_programs(s)
        seed_catalog(s)
        free = select(ProgramDeadline.program_id)
        first, second = s.scalars(select(Program.id).where(Program.id.not_in(free)).order_by(Program.id).limit(2)).all()

        def add(program_id: str, label: str | None, when: date, source: str, order: int) -> str:
            row = ProgramDeadline(id=str(uuid.uuid4()), program_id=program_id, label=label, deadline=when,
                                  quote=f"Deadline: {when.isoformat()}", source_url=source, sort_order=order)
            s.add(row)
            made.append(row.id)
            return row.id

        ids = {
            "round1": add(first, "Round 1", future(40), SOURCE, 0),
            "round2": add(first, "Round 2", future(90), SOURCE, 1),
            "other": add(second, "Main round", future(60), OTHER_SOURCE, 0),
        }
        s.commit()
    yield {"first": first, "second": second, **ids,
           "round1_date": future(40), "round2_date": future(90), "other_date": future(60)}
    with SessionLocal() as s:
        s.execute(delete(ProgramDeadline).where(ProgramDeadline.id.in_(made)))
        s.commit()


def new_applicant(programs: list[str] = ()) -> str:
    client_id = str(uuid.uuid4())
    with SessionLocal() as s:
        load_or_create_profile(s, client_id)
        if programs:
            replace_applications(s, client_id, [{"program_id": p, "tier": "稳"} for p in programs])
        s.commit()
    return client_id


@pytest.fixture
def applicant(catalogue) -> dict:
    """A subject with one catalogue application (the program with two rounds) and one manual one."""
    client_id = new_applicant([catalogue["first"]])
    with SessionLocal() as s:
        manual, _ = records.create_record(
            s, client_id, RecordCreate(school="Example University", name="Example MSc"), f"k-{uuid.uuid4().hex}"
        )
    return {"id": client_id, "config": config_of(client_id), "catalog": f"catalog:{catalogue['first']}",
            "manual": manual["id"], **catalogue}


def config_of(client_id: str, thread: str = "c1") -> dict:
    return {"configurable": {"client_id": client_id, "thread_id": f"{client_id}:{thread}"}}


def conversation(*said: str) -> dict:
    """The applicant's messages, sent today, as the stream stores them."""
    return {"messages": [HumanMessage(content=text, additional_kwargs=stated.stamp()) for text in said]}


def record(client_id: str, key: str) -> dict:
    with SessionLocal() as s:
        return records.read_record(s, client_id, key)


def all_records(client_id: str) -> list[dict]:
    with SessionLocal() as s:
        return records.read_records(client_id, s)


@pytest.fixture
def asked(monkeypatch) -> list[dict]:
    """Stub the confirm step: every question is recorded, and the applicant says yes, the way
    `routers.advisor` sends the answer back (with the changes and the base the question listed)."""
    questions: list[dict] = []

    def answer_yes(question):
        questions.append(question)
        return {"approved": True, "changes": question["changes"], "base": question.get("base")}

    monkeypatch.setattr(tools, "interrupt", answer_yes)
    return questions


@pytest.fixture
def declined(monkeypatch) -> list[dict]:
    questions: list[dict] = []

    def answer_no(question):
        questions.append(question)
        return {"approved": False, "changes": question["changes"], "base": question.get("base")}

    monkeypatch.setattr(tools, "interrupt", answer_no)
    return questions


def status(applicant: dict, key: str, value: str, **kwargs) -> str:
    return tools.propose_application_status.func(application_id=key, status=value, config=kwargs.pop("config", applicant["config"]))


def deadline(applicant: dict, key: str, said: tuple[str, ...] = (), **kwargs) -> str:
    return tools.propose_application_deadline.func(
        application_id=key, config=kwargs.pop("config", applicant["config"]), state=conversation(*said), **kwargs
    )


def tick(applicant: dict, key: str, said: tuple[str, ...] = (), **kwargs) -> str:
    return tools.propose_material_tick.func(
        application_id=key, config=kwargs.pop("config", applicant["config"]), state=conversation(*said), **kwargs
    )


def add_manual(client_id: str, school: str, name: str, call_id: str = "call-1", thread: str = "c1", said: tuple[str, ...] | None = None) -> str:
    said = (f"帮我加一个申请：{school} 的 {name}",) if said is None else said
    return tools.propose_manual_application.func(
        school=school, name=name, config=config_of(client_id, thread), state=conversation(*said), tool_call_id=call_id
    )


# ---------------------------------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------------------------------


def test_the_read_gives_round_deadline_its_check_source_status_and_material_flag(applicant):
    with SessionLocal() as s:
        base = records.read_record(s, applicant["id"], applicant["manual"])["version"]
        records.update_record(s, applicant["id"], applicant["manual"], RecordPatch(
            round="Round 1", deadline=date(2027, 1, 15), source_url="https://example.edu/apply",
            confirm_deadline=True, materials_ready=True, material_notes="推荐信两封", status="applying",
            base_version=base,
        ))
    rows = {r["id"]: r for r in json.loads(get_my_applications.invoke({}, config=applicant["config"]))}

    manual = rows[applicant["manual"]]
    assert manual["kind"] == "manual" and manual["programId"] is None
    assert (manual["round"], manual["deadline"], manual["sourceUrl"]) == ("Round 1", "2027-01-15", "https://example.edu/apply")
    assert manual["deadlineOrigin"] == "entered" and manual["deadlineCheckedByApplicant"] is True
    assert (manual["status"], manual["statusLabel"]) == ("applying", "准备中")
    assert manual["materialsReady"] is True and manual["materialNotes"] == "推荐信两封"
    assert "catalogDeadlines" not in manual

    catalog = rows[applicant["catalog"]]
    assert catalog["kind"] == "catalog" and catalog["programId"] == applicant["first"]
    # Nothing was chosen yet, so the read shows the catalogue's next date, marked as collected and unchecked.
    assert catalog["deadline"] == applicant["round1_date"].isoformat() and catalog["sourceUrl"] == SOURCE
    assert catalog["deadlineOrigin"] == "collected" and catalog["deadlineCheckedByApplicant"] is False
    assert catalog["round"] is None and catalog["materialsReady"] is False
    assert catalog["catalogDeadlines"] == [
        {"id": applicant["round1"], "round": "Round 1", "date": applicant["round1_date"].isoformat(), "sourceUrl": SOURCE, "passed": False},
        {"id": applicant["round2"], "round": "Round 2", "date": applicant["round2_date"].isoformat(), "sourceUrl": SOURCE, "passed": False},
    ]


def test_the_read_is_the_signed_in_applicant_s_own(applicant):
    stranger = new_applicant()
    assert json.loads(get_my_applications.invoke({}, config=config_of(stranger))) == []
    mine = get_my_applications.invoke({}, config=applicant["config"])
    assert "Example University" in mine


# ---------------------------------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------------------------------


def test_a_status_change_is_asked_first_and_written_once_confirmed(asked, applicant):
    before = record(applicant["id"], applicant["manual"])

    reply = status(applicant, applicant["manual"], "submitted")

    assert reply.startswith("已执行：")
    assert len(asked) == 1
    question = asked[0]
    assert question["tool"] == "propose_application_status" and question["type"] == "confirm_application"
    assert question["target"] == {"applicationId": applicant["manual"], "programId": None,
                                  "school": "Example University", "program": "Example MSc"}
    assert question["changes"] == [{"label": "申请状态", "before": "考虑中", "after": "已提交"}]
    assert question["base"]["version"] == before["version"]
    after = record(applicant["id"], applicant["manual"])
    assert after["status"] == "submitted"
    assert {k: v for k, v in after.items() if k not in ("status", "version")} == {
        k: v for k, v in before.items() if k not in ("status", "version")
    }


def test_a_catalogue_application_s_status_reaches_the_portfolio_row_too(asked, applicant):
    assert status(applicant, applicant["catalog"], "applying").startswith("已执行：")
    assert record(applicant["id"], applicant["catalog"])["status"] == "applying"
    with SessionLocal() as s:
        row = s.scalar(select(Application).where(Application.client_id == applicant["id"]))
        assert row.status == "applying"
    assert asked[0]["target"]["programId"] == applicant["first"]


def test_a_declined_status_change_writes_nothing(declined, applicant):
    before = record(applicant["id"], applicant["manual"])
    reply = status(applicant, applicant["manual"], "submitted")
    assert reply.startswith("用户取消了操作")
    assert len(declined) == 1
    assert record(applicant["id"], applicant["manual"]) == before


@pytest.mark.parametrize("value", ["waitlisted", "", "已提交"])
def test_a_status_the_record_cannot_hold_is_refused_before_asking(asked, applicant, value):
    before = record(applicant["id"], applicant["manual"])
    assert status(applicant, applicant["manual"], value).startswith("未执行：")
    assert asked == [] and record(applicant["id"], applicant["manual"]) == before


def test_a_status_it_already_has_is_not_put_to_the_applicant(asked, applicant):
    reply = status(applicant, applicant["manual"], "considering")
    assert reply.startswith("已是如此：") and "已经是" in reply and "考虑中" in reply
    assert asked == []


# ---------------------------------------------------------------------------------------------------
# One account cannot reach another's applications
# ---------------------------------------------------------------------------------------------------


def test_another_account_s_application_cannot_be_read_or_changed_through_the_arguments(asked, applicant, catalogue):
    stranger = {"id": new_applicant(), **catalogue}
    stranger["config"] = config_of(stranger["id"])
    before = all_records(applicant["id"])
    stated_date = future(120).isoformat()

    replies = [
        status(stranger, applicant["manual"], "submitted"),
        status(stranger, applicant["catalog"], "submitted"),
        deadline(stranger, applicant["manual"], (f"截止 {stated_date}",), stated_deadline=stated_date),
        deadline(stranger, applicant["catalog"], catalog_deadline_id=applicant["round2"]),
        tick(stranger, applicant["manual"], ready=True),
        tick(stranger, applicant["manual"], ("推荐信齐了",), add_note="推荐信齐了"),
    ]

    for reply in replies:
        assert reply.startswith("未执行：") and "没有这个申请" in reply
        # The refusal says nothing about the record: not its school, its status or that it exists.
        assert "Example" not in reply
    assert asked == []
    assert all_records(applicant["id"]) == before
    assert all_records(stranger["id"]) == []


def test_a_manual_application_is_added_to_the_caller_only(asked, applicant):
    stranger = new_applicant()
    assert add_manual(stranger, "Another University", "Another MSc").startswith("已执行：")
    assert [r["school"] for r in all_records(stranger)] == ["Another University"]
    assert "Another University" not in json.dumps(all_records(applicant["id"]), default=str)


# ---------------------------------------------------------------------------------------------------
# A deadline from the catalogue
# ---------------------------------------------------------------------------------------------------


def test_a_catalogue_round_is_written_with_its_date_and_source_and_stays_unchecked(asked, applicant):
    reply = deadline(applicant, applicant["catalog"], catalog_deadline_id=applicant["round2"])

    assert reply.startswith("已执行：")
    stored = record(applicant["id"], applicant["catalog"])
    assert stored["deadline"] == applicant["round2_date"] and stored["sourceUrl"] == SOURCE
    assert stored["round"] == "Round 2"
    # The catalogue's date, not the applicant's entry, and nobody has checked it.
    assert stored["deadlineOrigin"] == "collected" and stored["checkedAt"] is None
    labels = {c["label"]: c for c in asked[0]["changes"]}
    assert labels["轮次"] == {"label": "轮次", "before": None, "after": "Round 2"}
    assert labels["截止日期"]["before"] == applicant["round1_date"].isoformat()
    assert labels["截止日期"]["after"] == applicant["round2_date"].isoformat()
    assert "学校库" in labels["日期来源"]["after"] and "example.edu" in labels["日期来源"]["after"]
    assert "待核对" in labels["日期来源"]["after"]


def test_the_model_never_supplies_the_catalogue_s_date(asked, applicant):
    """In catalogue mode the date comes from the row on the server; a date sent beside it is refused."""
    made_up = future(200).isoformat()
    reply = deadline(applicant, applicant["catalog"], (f"截止 {made_up}",),
                     catalog_deadline_id=applicant["round2"], stated_deadline=made_up)
    assert reply.startswith("未执行：") and asked == []


@pytest.mark.parametrize("which", ["other", "missing"])
def test_a_catalogue_date_of_another_program_is_refused(asked, applicant, which):
    before = record(applicant["id"], applicant["catalog"])
    wrong = applicant["other"] if which == "other" else str(uuid.uuid4())
    reply = deadline(applicant, applicant["catalog"], catalog_deadline_id=wrong)
    assert reply.startswith("未执行：") and "学校库" in reply
    assert asked == [] and record(applicant["id"], applicant["catalog"]) == before


def test_a_manual_application_has_no_catalogue_date_to_take(asked, applicant):
    reply = deadline(applicant, applicant["manual"], catalog_deadline_id=applicant["round1"])
    assert reply.startswith("未执行：") and asked == []
    assert record(applicant["id"], applicant["manual"])["deadline"] is None


def test_a_checked_date_is_said_to_lose_its_check_when_the_round_changes(asked, applicant):
    key = applicant["catalog"]
    with SessionLocal() as s:
        base = records.read_record(s, applicant["id"], key)["version"]
        records.update_record(s, applicant["id"], key, RecordPatch(confirm_deadline=True, base_version=base))
    assert record(applicant["id"], key)["checkedAt"] is not None

    assert deadline(applicant, key, catalog_deadline_id=applicant["round2"]).startswith("已执行：")

    assert {"label": "核对状态", "before": "你核对过", "after": "待核对"} in asked[0]["changes"]
    assert record(applicant["id"], key)["checkedAt"] is None


def test_the_round_already_chosen_is_not_put_to_the_applicant(asked, applicant):
    assert deadline(applicant, applicant["catalog"], catalog_deadline_id=applicant["round2"]).startswith("已执行：")
    again = deadline(applicant, applicant["catalog"], catalog_deadline_id=applicant["round2"])
    assert again.startswith("已是如此：") and "已经是" in again
    assert len(asked) == 1


# ---------------------------------------------------------------------------------------------------
# A deadline the applicant stated
# ---------------------------------------------------------------------------------------------------


def test_a_date_the_applicant_stated_is_written_as_their_own_entry(asked, applicant):
    when = future(75)
    reply = deadline(applicant, applicant["manual"], (f"我这个项目的截止日期是 {when.isoformat()}",),
                     stated_deadline=when.isoformat())

    assert reply.startswith("已执行：")
    stored = record(applicant["id"], applicant["manual"])
    assert stored["deadline"] == when and stored["deadlineOrigin"] == "entered"
    assert stored["sourceUrl"] is None and stored["checkedAt"] is None
    labels = {c["label"]: c for c in asked[0]["changes"]}
    assert labels["截止日期"] == {"label": "截止日期", "before": None, "after": when.isoformat()}
    assert "你在对话里说的" in labels["日期来源"]["after"] and "待核对" in labels["日期来源"]["after"]


def test_a_stated_date_does_not_keep_the_catalogue_s_source(asked, applicant):
    """The catalogue's page was the source of the catalogue's date, not of the applicant's."""
    when = future(33)
    assert record(applicant["id"], applicant["catalog"])["sourceUrl"] == SOURCE

    assert deadline(applicant, applicant["catalog"], (f"官网改了，是 {when.isoformat()}",),
                    stated_deadline=when.isoformat()).startswith("已执行：")

    stored = record(applicant["id"], applicant["catalog"])
    assert stored["deadline"] == when and stored["sourceUrl"] is None and stored["deadlineOrigin"] == "entered"
    assert {"label": "来源链接", "before": SOURCE, "after": "不保留"} in asked[0]["changes"]
    # The date stops being the catalogue's, and the card says so.
    assert {"label": "日期来源", "before": "学校库采集", "after": "你在对话里说的，待核对"} in asked[0]["changes"]


def test_a_stated_date_keeps_a_source_the_applicant_entered(asked, applicant):
    with SessionLocal() as s:
        base = records.read_record(s, applicant["id"], applicant["manual"])["version"]
        records.update_record(s, applicant["id"], applicant["manual"], RecordPatch(
            deadline=future(20), source_url="https://example.edu/mine", base_version=base))
    when = future(21)
    assert deadline(applicant, applicant["manual"], (f"改成 {when.isoformat()}",),
                    stated_deadline=when.isoformat()).startswith("已执行：")
    stored = record(applicant["id"], applicant["manual"])
    assert stored["deadline"] == when and stored["sourceUrl"] == "https://example.edu/mine"
    assert "来源链接" not in [c["label"] for c in asked[0]["changes"]]


def test_a_round_the_applicant_named_is_written_in_their_words(asked, applicant):
    reply = deadline(applicant, applicant["manual"], ("我报的是 round 2",), stated_round="Round 2")
    assert reply.startswith("已执行：")
    assert record(applicant["id"], applicant["manual"])["round"] == "Round 2"
    assert asked[0]["changes"] == [{"label": "轮次", "before": None, "after": "Round 2"}]


MADE_UP = future(150).isoformat()


@pytest.mark.parametrize(
    "said, arguments",
    [
        # Nothing in the conversation at all.
        ((), {"stated_deadline": MADE_UP}),
        # The applicant asked for a date but did not give one.
        (("帮我把截止日期填上，你知道的那个就行",), {"stated_deadline": MADE_UP}),
        # A vague time is not a date the tool may make exact.
        (("截止大概是明年一月中旬",), {"stated_deadline": MADE_UP}),
        (("下周五截止",), {"stated_deadline": MADE_UP}),
        # A different date was stated.
        ((f"截止是 {future(151).isoformat()}",), {"stated_deadline": MADE_UP}),
        # Not a date.
        (("截止 2027-01-15",), {"stated_deadline": "明年一月"}),
        (("截止 2027-01-15",), {"stated_deadline": "2027-13-45"}),
        # A round the applicant never named.
        (("帮我填一下轮次",), {"stated_round": "Round 2"}),
        # A real round name beside a made-up date: neither is written.
        (("我报 Round 2",), {"stated_round": "Round 2", "stated_deadline": MADE_UP}),
        # Nothing to write.
        (("改一下截止日期",), {}),
        # A word that only contains the round's letters, and a date that only shares its digits.
        (("I'm looking at around 12 programs",), {"stated_round": "Round 1"}),
        ((f"见 https://example.edu/{MADE_UP.replace('-', '/')}/news",), {"stated_deadline": MADE_UP}),
    ],
)
def test_a_date_or_round_the_applicant_did_not_state_cannot_be_written(asked, applicant, said, arguments):
    for key in (applicant["manual"], applicant["catalog"]):
        before = record(applicant["id"], key)
        reply = deadline(applicant, key, said, **arguments)
        assert reply.startswith("未执行："), reply
        assert asked == []
        assert record(applicant["id"], key) == before


def test_a_date_only_the_advisor_or_a_tool_wrote_is_not_the_applicant_s(asked, applicant):
    state = {"messages": [
        HumanMessage(content="帮我把这个项目的截止日期记一下"),
        AIMessage(content=f"这个项目的截止日期应该是 {MADE_UP}。"),
        ToolMessage(content=json.dumps([{"deadline": MADE_UP}]), tool_call_id="c0"),
    ]}
    reply = tools.propose_application_deadline.func(
        application_id=applicant["manual"], config=applicant["config"], state=state, stated_deadline=MADE_UP)
    assert reply.startswith("未执行：") and asked == []
    assert record(applicant["id"], applicant["manual"])["deadline"] is None


def test_a_date_said_without_a_year_is_taken_as_its_next_occurrence_and_nothing_else(asked, applicant):
    today = stated.today()
    target = today + timedelta(days=45)
    said = (f"截止是 {target.month} 月 {target.day} 日",)
    a_year_on = target.replace(year=target.year + 1) if (target.month, target.day) != (2, 29) else None
    if a_year_on:
        refused = deadline(applicant, applicant["manual"], said, stated_deadline=a_year_on.isoformat())
        assert refused.startswith("未执行：") and asked == []
    assert deadline(applicant, applicant["manual"], said, stated_deadline=target.isoformat()).startswith("已执行：")
    assert record(applicant["id"], applicant["manual"])["deadline"] == target


def test_only_the_deadline_tool_can_carry_a_date_or_a_round():
    """Whatever the model writes into another tool's arguments, none of them is a deadline."""
    for tool in TOOLS:
        names = set(tool.tool_call_schema.model_json_schema().get("properties", {}))
        dated = {n for n in names if any(word in n for word in ("deadline", "date", "round", "source"))}
        if tool.name == "propose_application_deadline":
            assert dated == {"catalog_deadline_id", "stated_deadline", "stated_round"}
        else:
            assert dated == set(), tool.name


def test_the_advisor_never_marks_a_date_as_checked(asked, applicant):
    """`checked_at` is the applicant's own act in 「我的申请」; no tool argument sets it."""
    when = future(64)
    deadline(applicant, applicant["manual"], (f"我核对过官网了，截止 {when.isoformat()}",), stated_deadline=when.isoformat())
    deadline(applicant, applicant["catalog"], catalog_deadline_id=applicant["round2"])
    assert record(applicant["id"], applicant["manual"])["checkedAt"] is None
    assert record(applicant["id"], applicant["catalog"])["checkedAt"] is None


# ---------------------------------------------------------------------------------------------------
# Materials
# ---------------------------------------------------------------------------------------------------


def test_the_material_flag_is_ticked_and_unticked(asked, applicant):
    key = applicant["manual"]
    assert tick(applicant, key, ready=True).startswith("已执行：")
    assert record(applicant["id"], key)["materialsReady"] is True
    assert asked[0]["tool"] == "propose_material_tick"
    assert asked[0]["changes"] == [{"label": "材料", "before": "准备中", "after": "已就绪（自查）"}]

    assert tick(applicant, key, ready=True).startswith("已是如此：")  # already ticked
    assert len(asked) == 1

    assert tick(applicant, key, ready=False).startswith("已执行：")
    assert record(applicant["id"], key)["materialsReady"] is False
    assert asked[1]["changes"] == [{"label": "材料", "before": "已就绪（自查）", "after": "准备中"}]


def test_a_material_note_is_added_in_the_applicant_s_words_and_keeps_what_was_there(asked, applicant):
    key = applicant["catalog"]
    assert tick(applicant, key, ("记一下：推荐信已拿到两封",), add_note="推荐信已拿到两封").startswith("已执行：")
    assert tick(applicant, key, ("成绩单在办了",), add_note="成绩单在办了").startswith("已执行：")

    stored = record(applicant["id"], key)
    assert stored["materialNotes"] == "推荐信已拿到两封\n成绩单在办了"
    assert stored["materialsReady"] is False
    assert asked[1]["changes"] == [{"label": "材料备注", "before": None, "after": "加一行：成绩单在办了"}]


def test_a_note_the_applicant_did_not_write_is_refused(asked, applicant):
    """A note is where an invented requirement would otherwise be stored as the applicant's own."""
    reply = tick(applicant, applicant["manual"], ("帮我记一下材料要求",), add_note="需要三封推荐信，雅思 7.0")
    assert reply.startswith("未执行：") and asked == []
    assert record(applicant["id"], applicant["manual"])["materialNotes"] == ""


def test_a_material_change_with_nothing_in_it_is_refused(asked, applicant):
    assert tick(applicant, applicant["manual"]).startswith("未执行：")
    assert asked == []


def test_a_declined_material_change_writes_nothing(declined, applicant):
    before = record(applicant["id"], applicant["manual"])
    assert tick(applicant, applicant["manual"], ("推荐信齐了",), ready=True, add_note="推荐信齐了").startswith("用户取消了操作")
    assert record(applicant["id"], applicant["manual"]) == before


# ---------------------------------------------------------------------------------------------------
# Adding a manual application
# ---------------------------------------------------------------------------------------------------


def manual_rows(client_id: str) -> int:
    with SessionLocal() as s:
        return s.scalar(select(func.count()).select_from(ApplicationPlan).where(
            ApplicationPlan.client_id == client_id, ApplicationPlan.catalog_program_id.is_(None)))


def test_a_manual_application_is_added_once_confirmed_with_no_date(asked):
    client_id = new_applicant()
    reply = add_manual(client_id, " Some University ", "MSc Something")

    assert reply.startswith("已执行：")
    (stored,) = all_records(client_id)
    assert (stored["school"], stored["name"], stored["status"]) == ("Some University", "MSc Something", "considering")
    assert stored["deadline"] is None and stored["round"] is None and stored["sourceUrl"] is None
    assert stored["id"] in reply  # the model needs the id for a change that follows
    question = asked[0]
    assert question["tool"] == "propose_manual_application"
    assert question["target"] == {"applicationId": None, "programId": None, "school": "Some University", "program": "MSc Something"}
    assert question["changes"] == [
        {"label": "我的申请", "before": None, "after": "加入（手动添加）"},
        {"label": "申请状态", "before": None, "after": "考虑中"},
        {"label": "截止日期", "before": None, "after": "待确认"},
    ]


def test_the_same_confirmed_call_run_twice_adds_one_application(asked):
    """A step that is run again after a crash carries the same call id; the second run finds the first's row."""
    client_id = new_applicant()
    first = add_manual(client_id, "Some University", "MSc Something", call_id="call-7")
    again = add_manual(client_id, "Some University", "MSc Something", call_id="call-7")

    assert first.startswith("已执行：")
    assert again.startswith("已生效：") and "没有重复" in again
    assert manual_rows(client_id) == 1
    # Another call, in another conversation, is another application; the tool then sees the duplicate.
    other = add_manual(client_id, "Some University", "MSc Something", call_id="call-7", thread="c2")
    assert other.startswith("未执行：") and "已经有" in other
    assert manual_rows(client_id) == 1


def test_a_name_the_applicant_did_not_write_is_not_added(asked):
    """A name is free text: held to the applicant's words, it cannot carry a date or a round nobody stated."""
    client_id = new_applicant()
    said = ("帮我加一个申请：Some University 的 MSc Something",)
    smuggled = add_manual(client_id, "Some University", "MSc Something（Round 1，截止 2027-01-15）", said=said)
    expanded = add_manual(client_id, "Some University of Technology", "MSc Something", said=said)
    assert smuggled.startswith("未执行：") and expanded.startswith("未执行：")
    assert asked == [] and manual_rows(client_id) == 0
    assert add_manual(client_id, "some university", "MSc  Something", said=said).startswith("已执行：")


def test_a_program_added_from_another_conversation_meanwhile_is_not_added_twice(monkeypatch):
    """Two conversations hold a card for the same program. The second to be confirmed finds the first's record."""
    client_id = new_applicant()

    def yes_after_the_other_conversation(question):
        with SessionLocal() as s:
            records.create_record(s, client_id, RecordCreate(school="Some University", name="MSc Something"), f"k-{uuid.uuid4().hex}")
        return {"approved": True, "changes": question["changes"]}

    monkeypatch.setattr(tools, "interrupt", yes_after_the_other_conversation)
    reply = add_manual(client_id, "Some University", "MSc Something")
    assert reply.startswith("未执行：") and "已经有" in reply
    assert manual_rows(client_id) == 1


def test_a_declined_manual_application_is_not_added(declined):
    client_id = new_applicant()
    assert add_manual(client_id, "Some University", "MSc Something").startswith("用户取消了操作")
    assert manual_rows(client_id) == 0


@pytest.mark.parametrize("school, name", [("", "MSc"), ("  ", "MSc"), ("Some University", ""), ("x" * 201, "MSc")])
def test_a_manual_application_the_record_cannot_hold_is_refused_before_asking(asked, school, name):
    client_id = new_applicant()
    assert add_manual(client_id, school, name).startswith("未执行：")
    assert asked == [] and manual_rows(client_id) == 0


# ---------------------------------------------------------------------------------------------------
# A stale version
# ---------------------------------------------------------------------------------------------------


def test_a_change_confirmed_after_the_record_moved_is_not_written_and_says_what_moved(monkeypatch, applicant):
    """The card was drawn from one version; another device changed the record before the answer."""
    key, client_id = applicant["manual"], applicant["id"]
    questions: list[dict] = []

    def edited_elsewhere_then_yes(question):
        questions.append(question)
        with SessionLocal() as s:
            base = records.read_record(s, client_id, key)["version"]
            records.update_record(s, client_id, key, RecordPatch(round="Round 9", materials_ready=True, base_version=base))
        return {"approved": True, "changes": question["changes"], "base": question["base"]}

    monkeypatch.setattr(tools, "interrupt", edited_elsewhere_then_yes)

    reply = status(applicant, key, "submitted")

    assert reply.startswith("未执行：") and "别处" in reply
    # What moved, in the applicant's words: the round and the material flag, old value and new.
    assert "轮次" in reply and "Round 9" in reply and "材料" in reply and "已就绪" in reply
    stored = record(client_id, key)
    assert stored["status"] == "considering", "the stale change must not be written"
    assert stored["round"] == "Round 9" and stored["materialsReady"] is True, "the other device's edit stands"


def test_a_change_whose_own_field_moved_elsewhere_is_not_written_either(monkeypatch, applicant):
    key, client_id = applicant["manual"], applicant["id"]

    def submitted_elsewhere_then_yes(question):
        with SessionLocal() as s:
            base = records.read_record(s, client_id, key)["version"]
            records.update_record(s, client_id, key, RecordPatch(status="offered", base_version=base))
        return {"approved": True, "changes": question["changes"], "base": question["base"]}

    monkeypatch.setattr(tools, "interrupt", submitted_elsewhere_then_yes)
    reply = status(applicant, key, "submitted")
    assert reply.startswith("未执行：") and "收到录取" in reply
    assert record(client_id, key)["status"] == "offered"


def test_the_portfolio_change_states_the_rows_it_was_built_from(monkeypatch, applicant):
    """PR #94 left the advisor's portfolio write without a base: a row saved between its read and its
    write was replaced. The write now names the rows it read, and is refused when they have moved."""
    client_id = applicant["id"]
    monkeypatch.setattr(portfolio_tools, "interrupt", lambda question: {"approved": True, "changes": question["changes"]})
    real = portfolio_tools.replace_applications_based_on

    def another_device_saves_first(session, subject, rows, base):
        with SessionLocal() as other:
            replace_applications(other, subject, [{"program_id": applicant["first"], "tier": "冲", "status": "applying"}])
        return real(session, subject, rows, base)

    monkeypatch.setattr(portfolio_tools, "replace_applications_based_on", another_device_saves_first)

    reply = propose_portfolio_change.func(program_id=applicant["second"], action="add", tier="保", config=applicant["config"])

    assert reply.startswith("未执行：") and "别处" in reply
    with SessionLocal() as s:
        rows = {r.program_id: (r.tier, r.status) for r in s.scalars(select(Application).where(Application.client_id == client_id))}
    assert rows == {applicant["first"]: ("冲", "applying")}, "the other device's save stands and nothing was added"
