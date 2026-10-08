"""Seed the review criteria the Genuine Student review checks a statement against.

Every entry here is a transcription of the ten-point skeleton recorded in
`note/superpowers/specs/2026-10-06-stage-2-database-design.md` §6, which was itself read from the
Department of Home Affairs' Genuine Student requirement page on 2026-10-06. Nothing is added,
reworded into a new requirement, or given a threshold the page does not state: the point of a
criterion is that someone can check it, and a criterion nobody can trace is exactly the invented
requirement this project refuses to produce.

Two fields, two jobs:

- ``description`` carries the recorded statement, transcribed as it was written down;
- ``title`` is the short label the interface shows beside a finding, naming the subject the
  statement is about. It states no requirement of its own.

Every criterion is written as ``待核验`` with no verification date, because a machine seeding a table
is not a person checking a page. ``verified_at`` has no default anywhere in the schema for the same
reason, and the upsert below deliberately never writes either field once the row exists — the
operator command in ``review_cli.py`` is the only thing that may, and a re-seed must not undo it.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.review import CheckType, CriterionScope, CriterionStatus, ReviewCriterion
from app.models.source import Source
from app.seed_roadmap import GS_SOURCE_URL, seed_roadmap

# The criteria, in the order the recorded skeleton lists them. `rule` is null where only a person can
# judge the answer, which is nine of the ten.
GS_CRITERIA = [
    {
        "code": "gs-answer-length",
        "title": "回答长度",
        "description": "每题回答不超过 150 词。",
        "check_type": CheckType.LENGTH,
        "rule": {"maxWords": 150},
    },
    {
        "code": "gs-answer-language",
        "title": "回答语言",
        "description": "回答必须用英文。",
        "check_type": CheckType.LANGUAGE,
        "rule": None,
    },
    {
        "code": "gs-current-circumstances",
        "title": "当前情况",
        "description": "需说明当前情况：家庭、社区、就业、经济联系。",
        "check_type": CheckType.PRESENCE,
        "rule": None,
    },
    {
        "code": "gs-course-and-provider",
        "title": "课程与学校的选择",
        "description": "需说明为什么选这个课程与这个学校，并对课程要求与在澳生活有理解。",
        "check_type": CheckType.PRESENCE,
        "rule": None,
    },
    {
        "code": "gs-course-value",
        "title": "课程对个人的价值",
        "description": "需说明课程如何有利于本人。",
        "check_type": CheckType.PRESENCE,
        "rule": None,
    },
    {
        "code": "gs-evidence",
        "title": "陈述的证据支持",
        "description": "陈述需有证据支持：成绩单、雇主信息、税单或银行流水等。",
        "check_type": CheckType.EVIDENCE,
        "rule": None,
    },
    {
        "code": "gs-reason-not-home-country",
        "title": "不在本国就读的理由",
        "description": "若本国存在同类课程，需说明为何不在本国就读。",
        "check_type": CheckType.PRESENCE,
        "rule": None,
    },
    {
        "code": "gs-immigration-history",
        "title": "移民历史",
        "description": "移民历史：签证与旅行记录、以往的申请、拒签或取消记录。",
        "check_type": CheckType.PRESENCE,
        "rule": None,
    },
    {
        "code": "gs-minor-applicant",
        "title": "未成年申请人的附加考虑",
        "description": "未成年人另需考虑父母/法定监护人/配偶的意图。",
        "check_type": CheckType.PRESENCE,
        "rule": None,
    },
    {
        "code": "gs-applies-from",
        "title": "GS 的适用时间",
        "description": "GS 适用于 2024-03-23（含）之后递交的申请；该日期之前适用 GTE。",
        "check_type": CheckType.CONSISTENCY,
        "rule": None,
    },
]


def genuine_student_source_id(session: Session) -> str:
    """The page the visa materials already cite, created if it is not there yet.

    The criteria cite the same `sources` row rather than adding a second one with the same url, which
    the unique constraint would refuse anyway. Reaching for `seed_roadmap` rather than inserting the
    row here keeps one definition of that page: two rows with different titles for the same url is the
    kind of drift a provenance table exists to prevent.
    """
    source_id = session.execute(
        select(Source.id).where(Source.url == GS_SOURCE_URL)
    ).scalar_one_or_none()
    if source_id is None:
        seed_roadmap(session)
        source_id = session.execute(
            select(Source.id).where(Source.url == GS_SOURCE_URL)
        ).scalar_one_or_none()
    if source_id is None:  # pragma: no cover - `seed_roadmap` writes it unconditionally
        raise RuntimeError("the roadmap seed did not write the Genuine Student source")
    return source_id


def seed_review_criteria(session: Session) -> int:
    """Write the criteria and return how many are stored afterwards.

    Idempotent by ``code``. A row that already exists has its transcription refreshed — the page may
    have been re-read and the wording corrected — while ``status`` and ``verified_at`` are left exactly
    as they were found. That is the whole contract: this function may change what the source says, and
    may never change what a person decided about it.
    """
    source_id = genuine_student_source_id(session)
    for entry in GS_CRITERIA:
        stored = session.execute(
            select(ReviewCriterion).where(ReviewCriterion.code == entry["code"])
        ).scalar_one_or_none()
        if stored is None:
            session.add(
                ReviewCriterion(
                    id=str(uuid.uuid4()),
                    code=entry["code"],
                    scope=CriterionScope.GS,
                    title=entry["title"],
                    description=entry["description"],
                    check_type=entry["check_type"],
                    rule=entry["rule"],
                    source_id=source_id,
                    status=CriterionStatus.UNVERIFIED,
                )
            )
        else:
            stored.scope = CriterionScope.GS
            stored.title = entry["title"]
            stored.description = entry["description"]
            stored.check_type = entry["check_type"]
            stored.rule = entry["rule"]
            stored.source_id = source_id
    session.commit()
    return len(GS_CRITERIA)
