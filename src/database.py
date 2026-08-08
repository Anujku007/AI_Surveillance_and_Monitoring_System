"""
database.py
SQLite database setup and CRUD operations for the AI Surveillance System.

Tables:
    registered_persons  -> known individuals + their face embedding
    entry_exit_logs     -> every ENTRY/EXIT event, including unknown persons

Usage:
    from database import init_db, add_person, get_all_persons, log_event

    init_db()
    add_person("John Doe", "EMP001", "Engineering", embedding_vector)
    persons = get_all_persons()
    log_event(person_id=1, event_type="ENTRY", snapshot_path="logs/snapshots/1.jpg")
"""

import sqlite3
import numpy as np
from datetime import datetime

from config import DB_PATH
from error_handler import logger, error_context
from crypto import encrypt_bytes, decrypt_bytes


# ---------------------------------------------------------
# Connection helper
# ---------------------------------------------------------
def get_connection():
    """Returns a new SQLite connection with foreign keys enabled."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row  # access columns by name
    return conn


# ---------------------------------------------------------
# Schema setup
# ---------------------------------------------------------
def init_db():
    """Creates the required tables if they don't already exist."""
    with error_context("Initializing database"):
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS registered_persons (
                person_id       INTEGER PRIMARY KEY AUTOINCREMENT,
                name            TEXT NOT NULL,
                identifier      TEXT UNIQUE,      -- e.g. employee/roll ID
                organization    TEXT,
                embedding       BLOB NOT NULL,    -- 128-d face encoding, stored as bytes
                photo_path      TEXT,
                registered_at   TEXT NOT NULL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS entry_exit_logs (
                log_id          INTEGER PRIMARY KEY AUTOINCREMENT,
                person_id       INTEGER,          -- NULL if unknown/unmatched person
                event_type      TEXT NOT NULL CHECK (event_type IN ('ENTRY', 'EXIT')),
                timestamp       TEXT NOT NULL,
                camera_location TEXT DEFAULT 'Main Entrance',
                snapshot_path   TEXT,
                is_suspicious   INTEGER DEFAULT 0,  -- 1 if unmatched OR spoof-suspected
                reason          TEXT DEFAULT NULL,  -- 'unknown_face' | 'spoof_suspected' | 'repeat_offender' | NULL
                FOREIGN KEY (person_id) REFERENCES registered_persons (person_id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS unknown_watchlist (
                watch_id        INTEGER PRIMARY KEY AUTOINCREMENT,
                embedding       BLOB NOT NULL,
                first_seen      TEXT NOT NULL,
                last_seen       TEXT NOT NULL,
                sighting_count  INTEGER DEFAULT 1,
                last_snapshot   TEXT
            )
        """)

        conn.commit()
        conn.close()
        logger.info("Database initialized (tables ready)")
        _migrate_add_reason_column()


def _migrate_add_reason_column():
    """
    One-time migration: adds the 'reason' column to entry_exit_logs if the
    database was created before this column existed (safe to call every
    startup — it's a no-op once the column is already present).
    """
    with error_context("Checking database schema (reason column)"):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(entry_exit_logs)")
        columns = [row["name"] for row in cursor.fetchall()]
        if "reason" not in columns:
            cursor.execute("ALTER TABLE entry_exit_logs ADD COLUMN reason TEXT DEFAULT NULL")
            conn.commit()
            logger.info("Migrated database: added 'reason' column to entry_exit_logs")
        conn.close()


# ---------------------------------------------------------
# Registered persons — CRUD
# ---------------------------------------------------------
def add_person(name, identifier, organization, embedding, photo_path=None):
    """
    Registers a new known person.
    `embedding` should be a numpy array (128,) from face_recognition.
    Returns the new person_id, or None on failure.
    """
    with error_context(f"Adding person '{name}' to database"):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO registered_persons (name, identifier, organization, embedding, photo_path, registered_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            name,
            identifier,
            organization,
            encrypt_bytes(embedding.astype(np.float64).tobytes()),
            photo_path,
            datetime.now().isoformat()
        ))
        conn.commit()
        person_id = cursor.lastrowid
        conn.close()
        logger.info(f"Registered new person: {name} (ID: {identifier}) -> person_id={person_id}")
        return person_id


def get_all_persons():
    """
    Returns a list of dicts: {person_id, name, identifier, organization, embedding (np.array)}
    Used at startup to load all known faces into memory for comparison.
    """
    with error_context("Fetching all registered persons"):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM registered_persons")
        rows = cursor.fetchall()
        conn.close()

        persons = []
        for row in rows:
            try:
                decrypted = decrypt_bytes(row["embedding"])
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
        cursor.execute("SELECT * FROM registered_persons WHERE person_id = ?", (person_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None


def delete_person(person_id):
    with error_context(f"Deleting person_id={person_id}"):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM registered_persons WHERE person_id = ?", (person_id,))
        conn.commit()
        conn.close()
        logger.info(f"Deleted person_id={person_id}")


# ---------------------------------------------------------
# Entry/Exit logs — CRUD
# ---------------------------------------------------------
def log_event(person_id, event_type, camera_location="Main Entrance",
              snapshot_path=None, is_suspicious=False, reason=None):
    """
    Inserts a new ENTRY/EXIT log row.
    person_id can be None for unrecognized/suspicious individuals.
    reason: 'unknown_face' | 'spoof_suspected' | None (None = normal authorized event)
    """
    with error_context(f"Logging {event_type} event"):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO entry_exit_logs (person_id, event_type, timestamp, camera_location, snapshot_path, is_suspicious, reason)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            person_id,
            event_type,
            datetime.now().isoformat(),
            camera_location,
            snapshot_path,
            1 if is_suspicious else 0,
            reason
        ))
        conn.commit()
        log_id = cursor.lastrowid
        conn.close()

        who = f"person_id={person_id}" if person_id else "UNKNOWN person"
        logger.info(f"Logged {event_type} for {who} (log_id={log_id})")
        return log_id


def get_last_event_for_person(person_id):
    """
    Returns the most recent log row for a given person_id, or None.
    Used by the entry/exit state machine to decide ENTRY vs EXIT.
    """
    with error_context(f"Fetching last event for person_id={person_id}"):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
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
        cursor.execute("""
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
# Unknown-person watchlist — persists across sessions, so
# repeat unregistered visitors can be flagged over time
# ---------------------------------------------------------
def match_or_add_watchlist(embedding, snapshot_path, tolerance):
    """
    Compares `embedding` against everyone currently on the watchlist.
    If a close-enough match is found, increments their sighting count
    and returns (watch_id, sighting_count, is_new_entry=False).
    Otherwise, adds them as a new watchlist entry and returns
    (watch_id, 1, is_new_entry=True).
    """
    with error_context("Checking unknown-person watchlist"):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT watch_id, embedding, sighting_count FROM unknown_watchlist")
        rows = cursor.fetchall()

        best_id, best_dist, best_count = None, None, None
        for row in rows:
            try:
                stored_embedding = np.frombuffer(decrypt_bytes(row["embedding"]), dtype=np.float64)
            except ValueError:
                continue  # skip unreadable/legacy plaintext rows
            dist = np.linalg.norm(stored_embedding - embedding)
            if best_dist is None or dist < best_dist:
                best_dist = dist
                best_id = row["watch_id"]
                best_count = row["sighting_count"]

        now = datetime.now().isoformat()

        if best_id is not None and best_dist <= tolerance:
            new_count = best_count + 1
            cursor.execute("""
                UPDATE unknown_watchlist
                SET last_seen = ?, sighting_count = ?, last_snapshot = ?, embedding = ?
                WHERE watch_id = ?
            """, (now, new_count, snapshot_path, encrypt_bytes(embedding.astype(np.float64).tobytes()), best_id))
            conn.commit()
            conn.close()
            return best_id, new_count, False

        cursor.execute("""
            INSERT INTO unknown_watchlist (embedding, first_seen, last_seen, sighting_count, last_snapshot)
            VALUES (?, ?, ?, 1, ?)
        """, (encrypt_bytes(embedding.astype(np.float64).tobytes()), now, now, snapshot_path))
        conn.commit()
        watch_id = cursor.lastrowid
        conn.close()
        return watch_id, 1, True


def get_watchlist():
    """Returns all watchlist entries, most-seen first — useful for a dashboard view."""
    with error_context("Fetching watchlist"):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM unknown_watchlist ORDER BY sighting_count DESC, last_seen DESC")
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]


# ---------------------------------------------------------
# Quick manual test
# ---------------------------------------------------------
if __name__ == "__main__":
    init_db()
    print("Database ready at:", DB_PATH)