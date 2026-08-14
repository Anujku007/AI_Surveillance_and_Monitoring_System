"""
db_engine.py
Thin database-backend abstraction so database.py's business logic works
UNCHANGED against either backend:

    - "sqlite"     (default) — zero setup, used for local development
                    and single-machine demos.
    - "postgresql" — production-grade, handles concurrent writes safely
                    across multiple cameras/sites. The realistic choice
                    for a real multi-site deployment.

Switch backends via config.DB_BACKEND (set via the DB_BACKEND environment
variable in database/.env — requires an app restart to take effect, same
as other .env-based settings).

Business logic in database.py should ALWAYS write queries using '?' as the
placeholder character (SQLite style) and use insert_returning_id() instead
of relying on cursor.lastrowid directly — this module handles translating
both to whichever backend is actually active.
"""

from config import DB_BACKEND, DB_PATH, PG_HOST, PG_PORT, PG_DBNAME, PG_USER, PG_PASSWORD
from error_handler import logger

IS_POSTGRES = DB_BACKEND == "postgresql"

if IS_POSTGRES:
    import psycopg2
    import psycopg2.extras
else:
    import sqlite3


def get_connection():
    """Returns a new connection with dict-like row access (row["col"],
    dict(row)), regardless of backend."""
    if IS_POSTGRES:
        conn = psycopg2.connect(
            host=PG_HOST, port=PG_PORT, dbname=PG_DBNAME,
            user=PG_USER, password=PG_PASSWORD,
            cursor_factory=psycopg2.extras.RealDictCursor
        )
        return conn
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        return conn


def execute(cursor, query, params=()):
    """
    Executes a query written with '?' placeholders (SQLite style),
    auto-converting to '%s' for PostgreSQL. Query strings passed here
    must never contain a literal '?' character other than as a placeholder.
    """
    if IS_POSTGRES:
        query = query.replace("?", "%s")
    cursor.execute(query, params)
    return cursor


def insert_returning_id(cursor, query, params, id_column):
    """
    Executes an INSERT (written with '?' placeholders) and returns the
    new row's auto-generated ID, for either backend.
    """
    if IS_POSTGRES:
        query = query.replace("?", "%s") + f" RETURNING {id_column}"
        cursor.execute(query, params)
        return cursor.fetchone()[id_column]
    else:
        cursor.execute(query, params)
        return cursor.lastrowid


def pk_column(name):
    """CREATE TABLE column definition for an auto-incrementing primary key."""
    if IS_POSTGRES:
        return f"{name} SERIAL PRIMARY KEY"
    return f"{name} INTEGER PRIMARY KEY AUTOINCREMENT"


def blob_type():
    """Column type for storing raw encrypted bytes (face embeddings)."""
    return "BYTEA" if IS_POSTGRES else "BLOB"


def as_bytes(value):
    """Normalizes a fetched blob/bytea column to plain bytes — psycopg2
    returns BYTEA as a memoryview by default, sqlite3 already returns bytes."""
    return bytes(value) if value is not None else None


def get_table_columns(cursor, table_name):
    """Returns a list of column names for `table_name`, for either backend
    — used by the startup schema-migration checks."""
    if IS_POSTGRES:
        cursor.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
            (table_name,)
        )
        return [row["column_name"] for row in cursor.fetchall()]
    else:
        cursor.execute(f"PRAGMA table_info({table_name})")
        return [row["name"] for row in cursor.fetchall()]


logger.info(f"Database backend: {DB_BACKEND}")