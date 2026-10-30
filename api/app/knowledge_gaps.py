"""Review knowledge gaps from the server shell (openspec knowledge-gaps D6, D7).

    python -m app.knowledge_gaps list [--status open|recollect_queued|dismissed|all] [--limit N]
    python -m app.knowledge_gaps show <gap id>
    python -m app.knowledge_gaps review <gap id> recollect|dismiss [--note TEXT] [--school KEY]...

The same as the admin API, for production while login mode is off (no account can be an admin then).
A review made here records no reviewer account.
"""

import argparse
import json
import sys

from app.db import SessionLocal
from app.services import knowledge_gaps as kg
from app.services.refusals import Refused


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    listing = sub.add_parser("list")
    listing.add_argument("--status", default=kg.OPEN, choices=(*kg.STATUSES, "all"))
    listing.add_argument("--limit", type=int, default=100)
    show = sub.add_parser("show")
    show.add_argument("gap_id")
    review = sub.add_parser("review")
    review.add_argument("gap_id")
    review.add_argument("decision", choices=(kg.RECOLLECT, kg.DISMISS))
    review.add_argument("--note")
    review.add_argument("--school", action="append", dest="schools", help="collection key; repeat for several")
    args = parser.parse_args(argv)
    with SessionLocal() as session:
        try:
            if args.command == "list":
                out = {"gaps": kg.list_gaps(session, args.status, args.limit)}
            elif args.command == "show":
                out = kg.show_gap(session, args.gap_id)
            else:
                out = kg.review(session, args.gap_id, args.decision, note=args.note, school_keys=args.schools)
        except Refused as error:
            print(json.dumps({"error": error.status_code, "detail": error.detail}, ensure_ascii=False), file=sys.stderr)
            return 1
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
