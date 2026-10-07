"""Run the seeds from the command line: python seed_cli.py"""

from app.db import SessionLocal
from app.seed import seed_programs
from app.seed_roadmap import seed_roadmap

if __name__ == "__main__":
    with SessionLocal() as session:
        print(f"seeded {seed_programs(session)} programs")
        # Both counts are printed, so a run that adds nothing is distinguishable at a glance from a
        # run whose output was truncated.
        phases, materials = seed_roadmap(session)
        print(f"seeded {phases} roadmap phases and {materials} roadmap materials")
