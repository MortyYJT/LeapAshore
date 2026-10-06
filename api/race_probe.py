"""Measure how often `tests/test_first_contact_race.py` reproduces the first-contact collision.

This is the evidence tool behind the race test's discrimination claim: the regression test is only
worth having if it fails against the bare check-then-insert and passes against the savepoint fix.

    cd api && .venv/bin/python race_probe.py 20

Each round is a separate `pytest` process, so a round cannot inherit state from the one before it.
The tally is the last line.

To measure the other side, swap `app/deps.py` for the version before the fix:

    cp app/deps.py /tmp/deps-fixed.py
    git show 4e46879^:api/app/deps.py > app/deps.py   # 4e46879 added the savepoint
    .venv/bin/python race_probe.py 20
    cp /tmp/deps-fixed.py app/deps.py

The probe deliberately does not edit `app/deps.py` itself: a tool that rewrites tracked source during
a run leaves the fix reverted if it is interrupted, which is the one outcome this file must never
cause.
"""

import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
TEST = "tests/test_first_contact_race.py"


def main() -> int:
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    counts: Counter[str] = Counter()
    for index in range(1, rounds + 1):
        result = subprocess.run(
            [sys.executable, "-m", "pytest", TEST, "-q", "--no-header", "-p", "no:cacheprovider"],
            cwd=HERE,
            capture_output=True,
            text=True,
        )
        output = result.stdout + result.stderr
        if " skipped" in output:
            outcome = "skipped (is the database container running?)"
        elif result.returncode == 0:
            outcome = "passed"
        else:
            outcome = "FAILED"
        counts[outcome] += 1
        print(f"run {index:2d}: {outcome}", flush=True)
    print(f"rounds={rounds} {dict(counts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
