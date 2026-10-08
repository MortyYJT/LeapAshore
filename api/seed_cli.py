"""Run the seeds from the command line: python seed_cli.py"""

from app.db import SessionLocal
from app.seed import seed_programs
from app.seed_review_criteria import seed_review_criteria
from app.seed_roadmap import seed_roadmap

if __name__ == "__main__":
    with SessionLocal() as session:
        print(f"seeded {seed_programs(session)} programs")
        # Both counts are printed, so a run that adds nothing is distinguishable at a glance from a
        # run whose output was truncated.
        phases, materials = seed_roadmap(session)
        print(f"seeded {phases} roadmap phases and {materials} roadmap materials")
        # After the roadmap seed, whose Genuine Student source these criteria cite. The criteria seed
        # would create that source itself if it had to, so the order is a convenience rather than a
        # requirement.
        print(f"seeded {seed_review_criteria(session)} review criteria")
