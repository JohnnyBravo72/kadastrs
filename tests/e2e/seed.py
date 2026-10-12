"""Seed the kadastrs_test database for the end-to-end test (e2e/, Playwright):
the synthetic pilot of the batch tests (tests/batch/conftest.py).

    docker compose --profile test run --rm tests python -m tests.e2e.seed
"""

import psycopg

from tests.batch.conftest import seed_batch
from tests.etl.conftest import ETL_DB


def main() -> None:
    with psycopg.connect(ETL_DB) as conn:
        seed_batch(conn)
    print(f"seeded {ETL_DB.rsplit('/', 1)[-1]} for the end-to-end test")


if __name__ == "__main__":
    main()
