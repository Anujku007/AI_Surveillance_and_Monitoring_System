"""
auth.py
Simple single-admin authentication for the dashboard.

The password is never stored in plaintext — only a salted PBKDF2 hash is
saved to database/admin_auth.json. On first run (no password set yet),
the login screen prompts the user to create one.

Usage:
    from auth import is_password_set, set_password, verify_password

    if not is_password_set():
        set_password("choose-a-password")
    verify_password("choose-a-password")  -> True
"""

import os
import json
import hashlib
import secrets

from config import DATABASE_DIR

AUTH_FILE = os.path.join(DATABASE_DIR, "admin_auth.json")
PBKDF2_ITERATIONS = 100_000


def _hash_password(password, salt):
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS
    ).hex()


def is_password_set():
    return os.path.exists(AUTH_FILE)


def set_password(password):
    """Creates (or overwrites) the admin password, storing only its salted hash."""
    salt = secrets.token_bytes(16)
    hashed = _hash_password(password, salt)
    with open(AUTH_FILE, "w") as f:
        json.dump({"salt": salt.hex(), "hash": hashed}, f)


def verify_password(password):
    if not is_password_set():
        return False
    with open(AUTH_FILE) as f:
        data = json.load(f)
    salt = bytes.fromhex(data["salt"])
    return _hash_password(password, salt) == data["hash"]