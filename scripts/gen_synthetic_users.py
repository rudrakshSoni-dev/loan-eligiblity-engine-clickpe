"""Generate a seeded synthetic users CSV with the shape of the real sample.

The marginals come from docs/data-notes.md: monthly income 25,000-150,000 in steps of
1,000, credit score 650-800 in steps of 5, age 22-50 and three employment values, each
drawn uniformly and independently (measured correlations on the sample are below 0.02).
Every email ends in `@example.invalid`, so no generated row can reach a real mailbox.
"""

import argparse
import csv
import logging
import random
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

HEADER = ("user_id", "name", "email", "monthly_income", "credit_score", "employment_status", "age")
EMAIL_DOMAIN = "example.invalid"
INCOME_RANGE = range(25_000, 150_001, 1_000)
SCORE_RANGE = range(650, 801, 5)
AGE_RANGE = range(22, 51)
EMPLOYMENT_STATUSES = ("Salaried", "Self-Employed", "Business")
FIRST_NAMES = (
    "Aarav", "Ananya", "Arjun", "Diya", "Dhruv", "Isha", "Kabir", "Kavya", "Meera", "Neha",
    "Rohan", "Saanvi", "Shaurya", "Tara", "Vihaan", "Zoya", "Aditya", "Riya", "Vivaan", "Myra",
)  # fmt: skip
LAST_NAMES = (
    "Iyer", "Khan", "Pandey", "Sharma", "Verma", "Nair", "Reddy", "Gupta", "Mehta", "Bose",
    "Chopra", "Desai", "Joshi", "Kapoor", "Malhotra", "Patel", "Rao", "Singh", "Iyengar", "Menon",
)  # fmt: skip

logger = logging.getLogger("gen_synthetic_users")


def user_rows(count: int, seed: int) -> Iterator[tuple[str, str, str, int, int, str, int]]:
    """Yield `count` rows; the same seed always yields the same rows."""
    rng = random.Random(seed)
    for _ in range(count):
        first, last = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
        yield (
            str(uuid.UUID(int=rng.getrandbits(128), version=4)),
            f"{first} {last}",
            f"{first}.{last}@{EMAIL_DOMAIN}".lower(),
            rng.choice(INCOME_RANGE),
            rng.choice(SCORE_RANGE),
            rng.choice(EMPLOYMENT_STATUSES),
            rng.choice(AGE_RANGE),
        )


def write_csv(path: Path, count: int, seed: int) -> None:
    """Write the header and `count` rows to `path`."""
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(HEADER)
        writer.writerows(user_rows(count, seed))


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Read the command line."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--rows", type=int, default=100_000)
    parser.add_argument("--seed", type=int, default=20261022)
    parser.add_argument("--output", type=Path, default=Path("data/synthetic_100k.csv"))
    args = parser.parse_args(argv)
    if args.rows < 1:
        parser.error("--rows must be at least 1")
    return args


def main(argv: list[str]) -> int:
    """Generate the file and log its size."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = parse_args(argv)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_csv(args.output, args.rows, args.seed)
    logger.info(
        "wrote %s rows=%d seed=%d bytes=%d",
        args.output,
        args.rows,
        args.seed,
        args.output.stat().st_size,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
