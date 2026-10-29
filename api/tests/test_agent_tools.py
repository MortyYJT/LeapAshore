"""The advisor's portfolio tool, called the way the graph calls it but with the confirm step stubbed.

`propose_portfolio_change` stops the graph with `interrupt()` and writes only after the applicant
answers. Outside a running graph `interrupt` has nowhere to stop, so these tests replace it with a
stub that records the question and returns the applicant's answer. The writes are real: they go to
the development database, and the subjects are swept by `conftest`'s autouse fixture.
"""

import uuid

import pytest
from sqlalchemy import select

from app.agent import tools
from app.db import SessionLocal
from app.deps import load_or_create_profile
from app.models.application import Application
from app.models.program import Program
from app.services.applications import replace_applications

pytestmark = pytest.mark.usefixtures("require_db")


@pytest.fixture
def asked(monkeypatch) -> list[dict]:
    """Stub the confirm step: every question is recorded, and the applicant says yes."""
    questions: list[dict] = []

    def answer_yes(question):
        questions.append(question)
        return True

    monkeypatch.setattr(tools, "interrupt", answer_yes)
    return questions


@pytest.fixture
def applicant() -> dict:
    """A fresh subject whose portfolio holds two programs, the first of them its first choice."""
    client_id = str(uuid.uuid4())
    with SessionLocal() as s:
        first, second = s.scalars(select(Program.id).order_by(Program.id).limit(2)).all()
        load_or_create_profile(s, client_id)
        replace_applications(
            s,
            client_id,
            [
                {"program_id": first, "tier": "稳", "status": "applying", "is_primary": True},
                {"program_id": second, "tier": "冲", "status": "considering", "is_primary": False},
            ],
        )
    return {"config": {"configurable": {"client_id": client_id}}, "first": first, "second": second}


def _stored(client_id: str) -> dict[str, tuple]:
    with SessionLocal() as s:
        rows = s.scalars(select(Application).where(Application.client_id == client_id))
        return {r.program_id: (r.tier, r.status, r.is_primary) for r in rows}


def _call(applicant: dict, **kwargs) -> str:
    return tools.propose_portfolio_change.func(config=applicant["config"], **kwargs)


def test_recording_an_offer_changes_only_that_rows_status(asked, applicant):
    reply = _call(applicant, program_id=applicant["second"], action="set_status", status="offered")

    assert reply.startswith("已执行")
    assert "已获 offer" in asked[0]["summary"]
    client_id = applicant["config"]["configurable"]["client_id"]
    assert _stored(client_id) == {
        applicant["first"]: ("稳", "applying", True),
        applicant["second"]: ("冲", "offered", False),
    }


@pytest.mark.parametrize("status", ["submitted", "offered", "rejected", "excluded"])
def test_every_later_status_is_accepted(asked, applicant, status):
    reply = _call(applicant, program_id=applicant["first"], action="set_status", status=status)

    assert reply.startswith("已执行")
    client_id = applicant["config"]["configurable"]["client_id"]
    assert _stored(client_id)[applicant["first"]][1] == status


def test_an_unknown_status_is_refused_before_the_applicant_is_asked(asked, applicant):
    client_id = applicant["config"]["configurable"]["client_id"]
    before = _stored(client_id)

    reply = _call(applicant, program_id=applicant["first"], action="set_status", status="waitlisted")

    assert reply.startswith("未执行")
    assert asked == []
    assert _stored(client_id) == before


def test_a_status_for_a_program_outside_the_portfolio_is_refused(asked, applicant):
    with SessionLocal() as s:
        outside = s.scalar(
            select(Program.id).where(Program.id.not_in([applicant["first"], applicant["second"]])).limit(1)
        )

    reply = _call(applicant, program_id=outside, action="set_status", status="submitted")

    assert reply.startswith("未执行")
    assert asked == []


def test_a_declined_change_writes_nothing(monkeypatch, applicant):
    monkeypatch.setattr(tools, "interrupt", lambda question: False)
    client_id = applicant["config"]["configurable"]["client_id"]
    before = _stored(client_id)

    reply = _call(applicant, program_id=applicant["first"], action="set_status", status="rejected")

    assert reply.startswith("用户取消了操作")
    assert _stored(client_id) == before
