"""The operator command: the only writer of a verification date, and of a review.

Driven through `main(argv)` in-process rather than as a subprocess, so a failure is reported where it
happened instead of as an exit code with no traceback, and so the session under test is the one the
command writes to.

Each test asserts both halves of a refusal: the exit code the operator sees, and the state the
database is in afterwards. A command that printed an error and wrote the row anyway would pass a test
that only checked the exit code.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.main import app
from app.models.document import Document, DocumentStatus, DocumentVersion
from app.models.review import (
    CheckType,
    CriterionScope,
    CriterionStatus,
    DocumentReview,
    DocumentReviewFinding,
    FindingSeverity,
    ReviewCriterion,
    ReviewOverall,
)
from app.seed_review_criteria import seed_review_criteria
from app.services.documents import MIME_PNG
from review_cli import main
from tests.test_documents_service import A_PNG


@pytest.fixture(autouse=True)
def remove_the_criteria_these_tests_seed(clear_the_roadmap_definition_after_the_test):
    """Sweep the definition after each test here, as the other seeding modules do.

    `seed_review_criteria` commits and writes the Genuine Student source, which `test_sources.py`
    later inserts by url; leaving it behind makes that module fail on a unique violation for a
    reason that has nothing to do with what it tests.
    """


def an_upload(name: str = "陈述.png", data: bytes = A_PNG, content_type: str = MIME_PNG) -> dict:
    return {"file": (name, data, content_type)}


def a_material_under_review(kind: str = "gs") -> tuple[TestClient, str]:
    """A material ready to review, with the client that owns it.

    The client comes back with the id because the owner is the cookie that uploaded it: a test that
    made a second `TestClient` to add a version would be a second subject, and every later call would
    be answered 404 — measured while writing this file.
    """
    client = TestClient(app)
    document_id = client.post("/api/documents", files=an_upload()).json()["id"]
    assert client.post(f"/api/documents/{document_id}/archive", json={"kind": kind}).status_code == 200
    assert client.post(f"/api/documents/{document_id}/submit").status_code == 200
    return client, document_id


def status_of(document_id: str) -> str:
    with SessionLocal() as session:
        return session.get(Document, document_id).status


def reviews_of(document_id: str) -> list[DocumentReview]:
    with SessionLocal() as session:
        return list(
            session.scalars(
                select(DocumentReview).where(DocumentReview.document_id == document_id)
            )
        )


def findings_of(document_id: str) -> list[DocumentReviewFinding]:
    with SessionLocal() as session:
        return list(
            session.scalars(
                select(DocumentReviewFinding)
                .join(DocumentReview, DocumentReview.id == DocumentReviewFinding.review_id)
                .where(DocumentReview.document_id == document_id)
            )
        )


def test_verifying_a_criterion_stamps_the_moment_it_ran(db_session, require_db, capsys):
    seed_review_criteria(db_session)

    assert main(["verify-criterion", "gs-evidence"]) == 0

    with SessionLocal() as session:
        stored = session.execute(
            select(ReviewCriterion).where(ReviewCriterion.code == "gs-evidence")
        ).scalar_one()
    assert stored.status == CriterionStatus.VERIFIED
    assert stored.verified_at is not None, "a verified criterion must carry the date a person set"
    assert "已核验" in capsys.readouterr().out


def test_unverifying_a_criterion_clears_the_date(db_session, require_db):
    seed_review_criteria(db_session)
    main(["verify-criterion", "gs-evidence"])

    assert main(["unverify-criterion", "gs-evidence"]) == 0

    with SessionLocal() as session:
        stored = session.execute(
            select(ReviewCriterion).where(ReviewCriterion.code == "gs-evidence")
        ).scalar_one()
    assert stored.status == CriterionStatus.UNVERIFIED
    assert stored.verified_at is None


def test_verifying_a_criterion_that_does_not_exist_is_refused(db_session, require_db, capsys):
    seed_review_criteria(db_session)

    assert main(["verify-criterion", "no-such-criterion"]) == 1
    assert "找不到这条审核要点" in capsys.readouterr().err


def test_a_complete_review_is_recorded_and_moves_the_material(db_session, require_db, capsys):
    seed_review_criteria(db_session)
    _, document_id = a_material_under_review()

    code = main(
        [
            "review",
            document_id,
            "--version",
            "1",
            "--overall",
            ReviewOverall.NEEDS_REVISION,
            "--reviewed-by",
            "审查者",
            "--summary",
            "回答需要修改",
            "--finding",
            "gs-answer-length:warning:第二条回答 213 词，超过 150 词",
        ]
    )

    assert code == 0, capsys.readouterr().err
    assert status_of(document_id) == DocumentStatus.NEEDS_REVISION
    reviews = reviews_of(document_id)
    assert len(reviews) == 1
    assert reviews[0].reviewed_by == "审查者"
    assert reviews[0].version_id is not None
    findings = findings_of(document_id)
    assert len(findings) == 1
    assert findings[0].severity == FindingSeverity.WARNING
    assert findings[0].criterion_id is not None


def test_a_colon_inside_the_finding_text_survives(db_session, require_db):
    seed_review_criteria(db_session)
    _, document_id = a_material_under_review()

    assert (
        main(
            [
                "review",
                document_id,
                "--version",
                "1",
                "--overall",
                "needs_revision",
                "--reviewed-by",
                "审查者",
                "--finding",
                "gs-course-value:blocker:结论缺少理由：没有说明课程如何有利于本人",
            ]
        )
        == 0
    )

    stored = findings_of(document_id)[0]
    assert stored.finding == "结论缺少理由：没有说明课程如何有利于本人"


def test_a_passing_verdict_cannot_carry_a_blocker(db_session, require_db, capsys):
    seed_review_criteria(db_session)
    _, document_id = a_material_under_review()

    code = main(
        [
            "review",
            document_id,
            "--version",
            "1",
            "--overall",
            "pass",
            "--reviewed-by",
            "审查者",
            "--finding",
            "gs-evidence:blocker:没有提供任何证据",
        ]
    )

    assert code == 1
    assert "pass" in capsys.readouterr().err
    assert reviews_of(document_id) == []
    assert status_of(document_id) == DocumentStatus.UNDER_REVIEW


def test_a_failing_verdict_has_to_name_something(db_session, require_db, capsys):
    seed_review_criteria(db_session)
    _, document_id = a_material_under_review()

    assert (
        main(
            [
                "review",
                document_id,
                "--version",
                "1",
                "--overall",
                "needs_revision",
                "--reviewed-by",
                "审查者",
            ]
        )
        == 1
    )
    assert "至少要写一条具体建议" in capsys.readouterr().err
    assert reviews_of(document_id) == []


def test_a_severity_outside_the_set_is_refused(db_session, require_db, capsys):
    seed_review_criteria(db_session)
    _, document_id = a_material_under_review()

    assert (
        main(
            [
                "review",
                document_id,
                "--version",
                "1",
                "--overall",
                "needs_revision",
                "--reviewed-by",
                "审查者",
                "--finding",
                "gs-evidence:fatal:证据不足",
            ]
        )
        == 1
    )
    assert "严重程度" in capsys.readouterr().err
    assert reviews_of(document_id) == []


def test_a_review_without_an_attribution_is_refused(db_session, require_db, capsys):
    seed_review_criteria(db_session)
    _, document_id = a_material_under_review()

    assert (
        main(
            [
                "review",
                document_id,
                "--version",
                "1",
                "--overall",
                "insufficient_evidence",
                "--reviewed-by",
                "   ",
                "--finding",
                "gs-evidence:info:看不清楚",
            ]
        )
        == 1
    )
    assert "谁审的" in capsys.readouterr().err
    assert reviews_of(document_id) == []


def test_an_overall_outside_the_set_is_refused(db_session, require_db, capsys):
    seed_review_criteria(db_session)
    _, document_id = a_material_under_review()

    assert (
        main(
            [
                "review",
                document_id,
                "--version",
                "1",
                "--overall",
                "maybe",
                "--reviewed-by",
                "审查者",
                "--finding",
                "gs-evidence:info:看不清楚",
            ]
        )
        == 1
    )
    assert "pass" in capsys.readouterr().err
    assert reviews_of(document_id) == []


def test_a_criterion_from_another_scope_is_refused(db_session, require_db, capsys):
    """A conclusion about one kind of material cannot be justified by a requirement for another."""
    seed_review_criteria(db_session)
    _, document_id = a_material_under_review(kind="transcript")

    assert (
        main(
            [
                "review",
                document_id,
                "--version",
                "1",
                "--overall",
                "needs_revision",
                "--reviewed-by",
                "审查者",
                "--finding",
                "gs-answer-length:warning:超过 150 词",
            ]
        )
        == 1
    )
    assert "范围" in capsys.readouterr().err
    assert reviews_of(document_id) == []


def test_a_general_criterion_applies_to_any_material(db_session, require_db, capsys):
    seed_review_criteria(db_session)
    with SessionLocal() as session:
        source_id = session.execute(select(ReviewCriterion.source_id)).scalars().first()
        session.add(
            ReviewCriterion(
                id=str(uuid.uuid4()),
                code=f"general-{uuid.uuid4().hex[:8]}",
                scope=CriterionScope.GENERAL,
                title="通用要点",
                description="适用于任何材料",
                check_type=CheckType.PRESENCE,
                rule=None,
                source_id=source_id,
            )
        )
        session.commit()
        code = session.execute(
            select(ReviewCriterion.code).where(ReviewCriterion.scope == CriterionScope.GENERAL)
        ).scalars().first()

    _, document_id = a_material_under_review(kind="cv")
    try:
        assert (
            main(
                [
                    "review",
                    document_id,
                    "--version",
                    "1",
                    "--overall",
                    "needs_revision",
                    "--reviewed-by",
                    "审查者",
                    "--finding",
                    f"{code}:info:通用建议",
                ]
            )
            == 0
        ), capsys.readouterr().err
    finally:
        # The findings first: `document_review_findings.criterion_id` is RESTRICT, so a criterion that
        # a review cites cannot be deleted while that review exists.
        with SessionLocal() as session:
            row = session.execute(
                select(ReviewCriterion).where(ReviewCriterion.code == code)
            ).scalar_one()
            for finding in session.scalars(
                select(DocumentReviewFinding).where(DocumentReviewFinding.criterion_id == row.id)
            ):
                session.delete(finding)
            session.flush()
            session.delete(row)
            session.commit()


def test_a_superseded_version_cannot_be_reviewed(db_session, require_db, capsys):
    """The verdict describes bytes; a revision that arrived mid-review changes what is there.

    This is why the command makes the operator name the version instead of taking the current one: had
    it taken the current one, this review would have attached itself to a file nobody read.
    """
    seed_review_criteria(db_session)
    owner, document_id = a_material_under_review()

    appended = owner.post(
        f"/api/documents/{document_id}/versions",
        files=an_upload("陈述-第二版.png"),
    )
    assert appended.status_code == 201, appended.text
    with SessionLocal() as session:
        document = session.get(Document, document_id)
        document.status = DocumentStatus.UNDER_REVIEW
        session.commit()

    assert (
        main(
            [
                "review",
                document_id,
                "--version",
                "1",
                "--overall",
                "needs_revision",
                "--reviewed-by",
                "审查者",
                "--finding",
                "gs-answer-length:warning:超过 150 词",
            ]
        )
        == 1
    )
    assert "当前版本已经变了" in capsys.readouterr().err
    assert reviews_of(document_id) == []


def test_a_material_that_was_not_submitted_cannot_be_reviewed(db_session, require_db, capsys):
    seed_review_criteria(db_session)
    client = TestClient(app)
    document_id = client.post("/api/documents", files=an_upload()).json()["id"]
    client.post(f"/api/documents/{document_id}/archive", json={"kind": "gs"})

    assert (
        main(
            [
                "review",
                document_id,
                "--version",
                "1",
                "--overall",
                "insufficient_evidence",
                "--reviewed-by",
                "审查者",
                "--finding",
                "gs-evidence:info:看不清楚",
            ]
        )
        == 1
    )
    assert "不在送审状态" in capsys.readouterr().err
    assert reviews_of(document_id) == []


def test_an_inconclusive_review_leaves_the_material_under_review(db_session, require_db):
    """The review reached no conclusion, so the material is still waiting for one."""
    seed_review_criteria(db_session)
    _, document_id = a_material_under_review()

    assert (
        main(
            [
                "review",
                document_id,
                "--version",
                "1",
                "--overall",
                "insufficient_evidence",
                "--reviewed-by",
                "审查者",
                "--finding",
                "gs-immigration-history:info:没有提供旅行记录",
            ]
        )
        == 0
    )
    assert status_of(document_id) == DocumentStatus.UNDER_REVIEW
    assert len(reviews_of(document_id)) == 1


def test_a_passing_review_accepts_the_material(db_session, require_db):
    seed_review_criteria(db_session)
    _, document_id = a_material_under_review()

    assert (
        main(
            [
                "review",
                document_id,
                "--version",
                "1",
                "--overall",
                "pass",
                "--reviewed-by",
                "审查者",
                "--summary",
                "没有发现问题",
            ]
        )
        == 0
    )
    assert status_of(document_id) == DocumentStatus.ACCEPTED


def test_the_recorded_review_reaches_the_applicant_with_its_source(db_session, require_db):
    """End to end: what the operator wrote is what the owner reads, citation included."""
    seed_review_criteria(db_session)
    client = TestClient(app)
    document_id = client.post("/api/documents", files=an_upload()).json()["id"]
    client.post(f"/api/documents/{document_id}/archive", json={"kind": "gs"})
    client.post(f"/api/documents/{document_id}/submit")
    assert (
        main(
            [
                "review",
                document_id,
                "--version",
                "1",
                "--overall",
                "needs_revision",
                "--reviewed-by",
                "审查者",
                "--finding",
                "gs-answer-length:warning:第二条回答 213 词，超过 150 词",
            ]
        )
        == 0
    )

    body = client.get(f"/api/documents/{document_id}").json()

    assert body["status"] == "needs_revision"
    assert len(body["reviews"]) == 1
    review = body["reviews"][0]
    assert review["overall"] == "needs_revision"
    assert review["reviewedBy"] == "审查者"
    finding = review["findings"][0]
    assert finding["severity"] == "warning"
    assert finding["finding"] == "第二条回答 213 词，超过 150 词"
    assert finding["criterion"]["code"] == "gs-answer-length"
    assert finding["criterion"]["source"]["url"].startswith(
        "https://immi.homeaffairs.gov.au/"
    ), "a finding the applicant cannot check against the page is not a sourced finding"


def test_the_review_only_shows_on_the_owners_material(db_session, require_db):
    seed_review_criteria(db_session)
    client = TestClient(app)
    document_id = client.post("/api/documents", files=an_upload()).json()["id"]
    client.post(f"/api/documents/{document_id}/archive", json={"kind": "gs"})
    client.post(f"/api/documents/{document_id}/submit")
    main(
        [
            "review",
            document_id,
            "--version",
            "1",
            "--overall",
            "pass",
            "--reviewed-by",
            "审查者",
        ]
    )

    assert TestClient(app).get(f"/api/documents/{document_id}").status_code == 404


def test_the_review_names_the_version_it_judged(db_session, require_db):
    seed_review_criteria(db_session)
    _, document_id = a_material_under_review()
    main(
        [
            "review",
            document_id,
            "--version",
            "1",
            "--overall",
            "pass",
            "--reviewed-by",
            "审查者",
        ]
    )

    with SessionLocal() as session:
        review = session.execute(
            select(DocumentReview).where(DocumentReview.document_id == document_id)
        ).scalar_one()
        version = session.get(DocumentVersion, review.version_id)
        document = session.get(Document, document_id)
    assert version.version_no == 1
    assert document.current_version_id == version.id


def test_the_operator_can_find_the_material_they_were_asked_about(db_session, require_db, capsys):
    """`list` prints an id the `review` command then accepts, which is the whole point of it.

    Recording a review needs a document id, and the applicant's browser is the only place that knows
    one — the reviewer holds the database, not the cookie. Without this the operator would have to read
    the id out of the page's network tab, so the check is the round trip rather than the formatting:
    whatever `list` prints as the id has to be the id `review` takes.
    """
    seed_review_criteria(db_session)
    owner, document_id = a_material_under_review()

    assert main(["list"]) == 0
    printed = capsys.readouterr().out
    line = next((row for row in printed.splitlines() if document_id in row), None)
    assert line is not None, f"the material was not listed: {printed!r}"
    assert a_material_title(document_id) in line, "a row the operator cannot recognise is not a lead"
    assert "第 1 版" in line, "the version number is what `review --version` needs next"

    listed_id = line.split()[0]
    assert listed_id == document_id
    assert (
        main(
            [
                "review", listed_id,
                "--version", "1",
                "--overall", "pass",
                "--reviewed-by", "审查者",
            ]
        )
        == 0
    ), "the id the listing printed was not one the review command accepts"


def a_material_title(document_id: str) -> str:
    """The title the listing has to show for a material, read from the database."""
    with SessionLocal() as session:
        return session.get(Document, document_id).title
