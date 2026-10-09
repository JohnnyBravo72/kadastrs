"""Database connection pool for the API."""

import os

from psycopg_pool import ConnectionPool

DEFAULT_DATABASE_URL = "postgresql://kadastrs:kadastrs-dev@127.0.0.1:5432/kadastrs"


def database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


def create_pool() -> ConnectionPool:
    # wait=False: the API starts even if the DB is down; /health then reports it.
    return ConnectionPool(
        database_url(),
        min_size=1,
        max_size=5,
        open=False,
        check=ConnectionPool.check_connection,  # drop connections broken by a DB restart
        kwargs={"connect_timeout": 3, "application_name": "kadastrs-api"},
    )
