"""Run the program seed from the command line: python seed_cli.py"""

from app.db import SessionLocal
from app.seed import seed_programs

if __name__ == "__main__":
    with SessionLocal() as session:
        print(f"seeded {seed_programs(session)} programs")
