"""Run the review commands from the command line.

    python review_cli.py verify-criterion gs-evidence
    python review_cli.py unverify-criterion gs-evidence
    python review_cli.py review <document_id> --version 2 --overall needs_revision \
        --reviewed-by <handle> --summary "..." --finding "gs-answer-length:warning:第二条回答 213 词"

**Why a command rather than a route.** This repository has no login and no role: the API addresses an
anonymous device cookie, and every HTTP write route is therefore reachable by anyone who can reach the
site. Two operations here must not be — marking a requirement as verified, and recording a verdict on
someone's material — because `verified_at` is a promise that a person checked a page, and a verdict is a
claim about an applicant's application. A command runs on the machine that holds the database, which is
the only place with standing to say either.

**The message a refusal prints** is the same one the API would return, because both come from
`app.services.reviews`; this file only parses arguments and reports what the service decided.
"""

import argparse
import sys

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.document import DocumentVersion
from app.services.refusals import Refused
from app.services.reviews import recent_materials, record_review, verify_criterion


def _parse_finding(value: str) -> dict:
    """One ``--finding`` argument as a finding.

    Split on the first two colons only: the code and the severity are from fixed vocabularies and
    cannot contain one, while the text is Chinese prose that very often does ("结论：需要补充"). A
    three-way split that kept the remainder together is what makes a colon in the text survive; a
    split on every colon would silently truncate the operator's own words.
    """
    parts = value.split(":", 2)
    if len(parts) != 3:
        raise argparse.ArgumentTypeError(
            f"建议的格式是 <要点代码>:<严重程度>:<具体建议>，收到的是 {value!r}"
        )
    code, severity, finding = (part.strip() for part in parts)
    if not code or not severity or not finding:
        raise argparse.ArgumentTypeError(f"建议的三段都不能为空：{value!r}")
    return {"code": code, "severity": severity, "finding": finding}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OfferPilot 审核依据与审核结论的维护命令")
    commands = parser.add_subparsers(dest="command", required=True)

    for name, help_text in (
        ("verify-criterion", "标记一条审核要点为已核验（写入当前时间）"),
        ("unverify-criterion", "把一条审核要点退回待核验"),
    ):
        verify = commands.add_parser(name, help=help_text)
        verify.add_argument("code", help="审核要点的代码，例如 gs-evidence")

    listing = commands.add_parser(
        "list", help="列出最近上传的材料，用来找 review 需要的那份 id"
    )
    listing.add_argument("--limit", type=int, default=20, help="最多列几条，默认 20")

    review = commands.add_parser("review", help="写入一条审核结论")
    review.add_argument("document_id", help="材料的 id")
    review.add_argument(
        "--version",
        type=int,
        required=True,
        help="这份结论审的是第几版；必须是当前版本，否则拒绝",
    )
    review.add_argument("--overall", required=True, help="pass / needs_revision / insufficient_evidence")
    review.add_argument("--reviewed-by", required=True, help="谁审的")
    review.add_argument("--summary", default=None, help="结论摘要")
    review.add_argument(
        "--finding",
        action="append",
        default=[],
        type=_parse_finding,
        help="可重复：<要点代码>:<严重程度>:<具体建议>",
    )
    return parser


def main(argv: list[str] | None = None, session: Session | None = None) -> int:
    """Run one command and return the process exit code.

    A session may be passed in so a test can drive the command against its own connection; without one
    this opens the application's own.
    """
    args = build_parser().parse_args(argv)
    owns_session = session is None
    session = session or SessionLocal()
    try:
        if args.command == "verify-criterion":
            criterion = verify_criterion(session, args.code, verified=True)
            print(f"已核验 {criterion.code}，核验时间 {criterion.verified_at.isoformat()}")
        elif args.command == "unverify-criterion":
            criterion = verify_criterion(session, args.code, verified=False)
            print(f"已退回待核验 {criterion.code}")
        elif args.command == "list":
            materials = recent_materials(session, limit=args.limit)
            if not materials:
                print("还没有任何材料。")
            for material in materials:
                version = (
                    session.get(DocumentVersion, material.current_version_id)
                    if material.current_version_id is not None
                    else None
                )
                print(
                    f"{material.id}  {material.status:<14} {material.kind or '未分类':<26} "
                    f"{material.title}（{material.created_at:%Y-%m-%d}，"
                    f"主体 {material.client_id[:8]}…，"
                    f"{'第 %d 版 %s' % (version.version_no, version.filename) if version else '还没有文件'}）"
                )
        else:
            review = record_review(
                session,
                args.document_id,
                version_no=args.version,
                overall=args.overall,
                reviewed_by=args.reviewed_by,
                summary=args.summary,
                findings=args.finding,
            )
            print(
                f"已写入审核结论 {review.id}：{review.overall}，"
                f"建议 {len(args.finding)} 条，审阅人 {review.reviewed_by}"
            )
        return 0
    except Refused as refused:
        print(refused.detail, file=sys.stderr)
        return 1
    finally:
        if owns_session:
            session.close()


if __name__ == "__main__":
    raise SystemExit(main())
