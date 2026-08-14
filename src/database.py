"""
database.py
Database setup and CRUD operations for the AI Surveillance System.
Works against either SQLite (default) or PostgreSQL — see db_engine.py
for the backend abstraction and config.DB_BACKEND to switch.

Tables:
    registered_persons  -> known individuals + their encrypted face embedding
    entry_exit_logs      -> every ENTRY/EXIT event, including unknown persons
    unknown_watchlist    -> persistent cross-session tracking of unregistered
                            visitors, for repeat-offender detection
    users                -> multi-account authentication with roles
    audit_log             -> accountability trail of sensitive actions

Usage:
    from database import init_db, add_person, get_all_persons, log_event

    init_db()
    add_person("John Doe", "EMP001", "Engineering", embedding_vector, consent_given=True)
    persons = get_all_persons()
    log_event(person_id=1, event_type="ENTRY", snapshot_path="logs/snapshots/1.jpg")
"""

import numpy as np
from datetime import datetime, timedelta

from config import DB_BACKEND
from error_handler import logger, error_context
from crypto import encrypt_bytes, decrypt_bytes
from db_engine import (
    get_connection, execute, insert_returning_id,
    pk_column, blob_type, as_bytes, get_table_columns
)


# ---------------------------------------------------------
# Schema setup
# ---------------------------------------------------------
def init_db():
    """Creates the required tables if they don't already exist."""
    with error_context("Initializing database"):
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS registered_persons (
                {pk_column('person_id')},
                name            TEXT NOT NULL,
                identifier      TEXT UNIQUE,
                organization    TEXT,
                embedding       {blob_type()} NOT NULL,
                photo_path      TEXT,
                registered_at   TEXT NOT NULL
            )
        """)

        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS entry_exit_logs (
                {pk_column('log_id')},
                person_id       INTEGER,
                event_type      TEXT NOT NULL CHECK (event_type IN ('ENTRY', 'EXIT')),
                timestamp       TEXT NOT NULL,
                camera_location TEXT DEFAULT 'Main Entrance',
                snapshot_path   TEXT,
                is_suspicious   INTEGER DEFAULT 0,
                FOREIGN KEY (person_id) REFERENCES registered_persons (person_id)
            )
        """)

        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS unknown_watchlist (
                {pk_column('watch_id')},
                embedding       {blob_type()} NOT NULL,
                first_seen      TEXT NOT NULL,
                last_seen       TEXT NOT NULL,
                sighting_count  INTEGER DEFAULT 1,
                last_snapshot   TEXT
            )
        """)

        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS users (
                {pk_column('user_id')},
                username        TEXT UNIQUE NOT NULL,
                salt            TEXT NOT NULL,
                password_hash   TEXT NOT NULL,
                role            TEXT NOT NULL CHECK (role IN ('admin', 'guard', 'viewer')),
                created_at      TEXT NOT NULL
            )
        """)

        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS audit_log (
                {pk_column('audit_id')},
                username        TEXT,
                action          TEXT NOT NULL,
                details         TEXT,
                timestamp       TEXT NOT NULL
            )
        """)

        conn.commit()
        conn.close()
        logger.info(f"Database initialized (tables ready) — backend: {DB_BACKEND}")
        _migrate_add_reason_column()
        _migrate_add_consent_columns()


def _migrate_add_reason_column():
    with error_context("Checking database schema (reason column)"):
        conn = get_connection()
        cursor = conn.cursor()
        columns = get_table_columns(cursor, "entry_exit_logs")
        if "reason" not in columns:
            cursor.execute("ALTER TABLE entry_exit_logs ADD COLUMN reason TEXT DEFAULT NULL")
            conn.commit()
            logger.info("Migrated database: added 'reason' column to entry_exit_logs")
        conn.close()


def _migrate_add_consent_columns():
    with error_context("Checking database schema (consent columns)"):
        conn = get_connection()
        cursor = conn.cursor()
        columns = get_table_columns(cursor, "registered_persons")
        if "consent_given" not in columns:
            cursor.execute("ALTER TABLE registered_persons ADD COLUMN consent_given INTEGER DEFAULT 0")
            cursor.execute("ALTER TABLE registered_persons ADD COLUMN consent_at TEXT DEFAULT NULL")
            conn.commit()
            logger.info("Migrated database: added consent columns to registered_persons")
        conn.close()


# ---------------------------------------------------------
# Registered persons — CRUD
# ---------------------------------------------------------
def add_person(name, identifier, organization, embedding, photo_path=None, consent_given=False):
    """
    Registers a new known person. `embedding` is a numpy array (128,).
    `consent_given` should be True only if the person explicitly consented
    to having their face registered — required for privacy compliance.
    Returns the new person_id, or None on failure.
    """
    with error_context(f"Adding person '{name}' to database"):
        conn = get_connection()
        cursor = conn.cursor()
        encrypted = encrypt_bytes(embedding.astype(np.float64).tobytes())

        person_id = insert_returning_id(cursor, """
            INSERT INTO registered_persons
                (name, identifier, organization, embedding, photo_path, registered_at, consent_given, consent_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            name, identifier, organization, encrypted, photo_path,
            datetime.now().isoformat(),
            1 if consent_given else 0,
            datetime.now().isoformat() if consent_given else None
        ), "person_id")

        conn.commit()
        conn.close()
        logger.info(f"Registered new person: {name} (ID: {identifier}) -> person_id={person_id}")
        return person_id


def get_all_persons():
    """Returns a list of dicts: {person_id, name, identifier, organization, embedding (np.array)}."""
    with error_context("Fetching all registered persons"):
        conn = get_connection()
        cursor = conn.cursor()
        execute(cursor, "SELECT * FROM registered_persons")
        rows = cursor.fetchall()
        conn.close()

        persons = []
        for row in rows:
            try:
                decrypted = decrypt_bytes(as_bytes(row["embedding"]))
            except ValueError as e:
                logger.warning(f"Skipping person_id={row['person_id']} ({row['name']}): {e}")
                continue
            persons.append({
                "person_id": row["person_id"],
                "name": row["name"],
                "identifier": row["identifier"],
                "organization": row["organization"],
                "embedding": np.frombuffer(decrypted, dtype=np.float64),
                "photo_path": row["photo_path"],
            })
        return persons


def get_person_by_id(person_id):
    with error_context(f"Fetching person_id={person_id}"):
        conn = get_connection()
        cursor = conn.cursor()
        execute(cursor, "SELECT * FROM registered_persons WHERE person_id = ?", (person_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None


def delete_person(person_id):
    with error_context(f"Deleting person_id={person_id}"):
        conn = get_connection()
        cursor = conn.cursor()
        execute(cursor, "DELETE FROM registered_persons WHERE person_id = ?", (person_id,))
        conn.commit()
        conn.close()
        logger.info(f"Deleted person_id={person_id}")


# ---------------------------------------------------------
# Entry/Exit logs — CRUD
# ---------------------------------------------------------
def log_event(person_id, event_type, camera_location="Main Entrance",
              snapshot_path=None, is_suspicious=False, reason=None):
    """Inserts a new ENTRY/EXIT log row. person_id can be None for unrecognized persons."""
    with error_context(f"Logging {event_type} event"):
        conn = get_connection()
        cursor = conn.cursor()

        log_id = insert_returning_id(cursor, """
            INSERT INTO entry_exit_logs
                (person_id, event_type, timestamp, camera_location, snapshot_path, is_suspicious, reason)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            person_id, event_type, datetime.now().isoformat(), camera_location,
            snapshot_path, 1 if is_suspicious else 0, reason
        ), "log_id")

        conn.commit()
        conn.close()

        who = f"person_id={person_id}" if person_id else "UNKNOWN person"
        logger.info(f"Logged {event_type} for {who} (log_id={log_id})")
        return log_id


def get_last_event_for_person(person_id):
    with error_context(f"Fetching last event for person_id={person_id}"):
        conn = get_connection()
        cursor = conn.cursor()
        execute(cursor, """
            SELECT * FROM entry_exit_logs
            WHERE person_id = ?
            ORDER BY timestamp DESC
            LIMIT 1
        """, (person_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None


def get_all_logs(limit=100):
    """Returns the most recent N log entries, joined with person name for display."""
    with error_context("Fetching recent logs"):
        conn = get_connection()
        cursor = conn.cursor()
        execute(cursor, """
            SELECT l.log_id, l.event_type, l.timestamp, l.camera_location,
                   l.is_suspicious, l.reason, l.snapshot_path,
                   p.name, p.identifier
            FROM entry_exit_logs l
            LEFT JOIN registered_persons p ON l.person_id = p.person_id
            ORDER BY l.timestamp DESC
            LIMIT ?
        """, (limit,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]


# ---------------------------------------------------------
# Unknown-person watchlist — persists across sessions
# ---------------------------------------------------------
def match_or_add_watchlist(embedding, snapshot_path, tolerance):
    """
    Compares `embedding` against everyone currently on the watchlist.
    Returns (watch_id, sighting_count, is_new_entry).
    """
    with error_context("Checking unknown-person watchlist"):
        conn = get_connection()
        cursor = conn.cursor()
        execute(cursor, "SELECT watch_id, embedding, sighting_count FROM unknown_watchlist")
        rows = cursor.fetchall()

        best_id, best_dist, best_count = None, None, None
        for row in rows:
            try:
                stored_embedding = np.frombuffer(decrypt_bytes(as_bytes(row["embedding"])), dtype=np.float64)
            except ValueError:
                continue  # skip unreadable/legacy rows
            dist = np.linalg.norm(stored_embedding - embedding)
            if best_dist is None or dist < best_dist:
                best_dist = dist
                best_id = row["watch_id"]
                best_count = row["sighting_count"]

        now = datetime.now().isoformat()
        encrypted = encrypt_bytes(embedding.astype(np.float64).tobytes())

        if best_id is not None and best_dist <= tolerance:
            new_count = best_count + 1
            execute(cursor, """
                UPDATE unknown_watchlist
                SET last_seen = ?, sighting_count = ?, last_snapshot = ?, embedding = ?
                WHERE watch_id = ?
            """, (now, new_count, snapshot_path, encrypted, best_id))
            conn.commit()
            conn.close()
            return best_id, new_count, False

        watch_id = insert_returning_id(cursor, """
            INSERT INTO unknown_watchlist (embedding, first_seen, last_seen, sighting_count, last_snapshot)
            VALUES (?, ?, ?, 1, ?)
        """, (encrypted, now, now, snapshot_path), "watch_id")
        conn.commit()
        conn.close()
        return watch_id, 1, True


def get_watchlist():
    with error_context("Fetching watchlist"):
        conn = get_connection()
        cursor = conn.cursor()
        execute(cursor, "SELECT * FROM unknown_watchlist ORDER BY sighting_count DESC, last_seen DESC")
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]


# ---------------------------------------------------------
# Users (multi-account authentication with roles)
# ---------------------------------------------------------
from password_utils import hash_password, verify_password as _verify_password_hash


def any_users_exist():
    with error_context("Checking if any users exist"):
        conn = get_connection()
        cursor = conn.cursor()
        execute(cursor, "SELECT COUNT(*) as c FROM users")
        count = cursor.fetchone()["c"]
        conn.close()
        return count > 0


def create_user(username, password, role):
    with error_context(f"Creating user '{username}'"):
        salt, pw_hash = hash_password(password)
        conn = get_connection()
        cursor = conn.cursor()
        user_id = insert_returning_id(cursor, """
            INSERT INTO users (username, salt, password_hash, role, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (username, salt, pw_hash, role, datetime.now().isoformat()), "user_id")
        conn.commit()
        conn.close()
        logger.info(f"Created user '{username}' with role '{role}'")
        return user_id


def verify_login(username, password):
    """Returns {user_id, username, role} on success, or None on failure."""
    with error_context(f"Verifying login for '{username}'"):
        conn = get_connection()
        cursor = conn.cursor()
        execute(cursor, "SELECT * FROM users WHERE username = ?", (username,))
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        if _verify_password_hash(password, row["salt"], row["password_hash"]):
            return {"user_id": row["user_id"], "username": row["username"], "role": row["role"]}
        return None


def get_all_users():
    with error_context("Fetching all users"):
        conn = get_connection()
        cursor = conn.cursor()
        execute(cursor, "SELECT user_id, username, role, created_at FROM users ORDER BY created_at")
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]


def delete_user(user_id):
    with error_context(f"Deleting user_id={user_id}"):
        conn = get_connection()
        cursor = conn.cursor()
        execute(cursor, "DELETE FROM users WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
        logger.info(f"Deleted user_id={user_id}")


# ---------------------------------------------------------
# Audit log
# ---------------------------------------------------------
def log_audit(username, action, details=""):
    with error_context(f"Logging audit event: {action}"):
        conn = get_connection()
        cursor = conn.cursor()
        execute(cursor, """
            INSERT INTO audit_log (username, action, details, timestamp)
            VALUES (?, ?, ?, ?)
        """, (username, action, details, datetime.now().isoformat()))
        conn.commit()
        conn.close()


def get_audit_log(limit=200):
    with error_context("Fetching audit log"):
        conn = get_connection()
        cursor = conn.cursor()
        execute(cursor, "SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT ?", (limit,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]


# ---------------------------------------------------------
# Data retention — purge old logs/snapshots/watchlist entries
# ---------------------------------------------------------
def purge_old_data(retention_days):
    """
    Deletes entry_exit_logs rows (and their snapshot files) older than
    `retention_days`, plus stale unknown_watchlist entries.
    Returns a summary dict of how much was removed.
    """
    import os as _os
    with error_context(f"Purging data older than {retention_days} days"):
        cutoff = (datetime.now() - timedelta(days=retention_days)).isoformat()

        conn = get_connection()
        cursor = conn.cursor()

        execute(cursor, "SELECT log_id, snapshot_path FROM entry_exit_logs WHERE timestamp < ?", (cutoff,))
        old_logs = cursor.fetchall()

        deleted_files = 0
        for row in old_logs:
            path = row["snapshot_path"]
            if path and _os.path.exists(path):
                try:
                    _os.remove(path)
                    deleted_files += 1
                except Exception as e:
                    logger.warning(f"Could not delete snapshot {path}: {e}")

        execute(cursor, "DELETE FROM entry_exit_logs WHERE timestamp < ?", (cutoff,))
        deleted_logs = cursor.rowcount

        execute(cursor, "DELETE FROM unknown_watchlist WHERE last_seen < ?", (cutoff,))
        deleted_watchlist = cursor.rowcount

        conn.commit()
        conn.close()

        logger.info(
            f"Data retention purge: removed {deleted_logs} log(s), "
            f"{deleted_files} snapshot file(s), {deleted_watchlist} watchlist entry(ies) "
            f"older than {retention_days} days."
        )
        return {"deleted_logs": deleted_logs, "deleted_files": deleted_files, "deleted_watchlist": deleted_watchlist}


# ---------------------------------------------------------
# Quick manual test
# ---------------------------------------------------------
if __name__ == "__main__":
    init_db()
    print(f"Database ready — backend: {DB_BACKEND}")