"""
password_utils.py
Shared salted-hash password utilities (PBKDF2-SHA256), used by the
multi-user authentication system in database.py.
"""

import hashlib
import secrets

PBKDF2_ITERATIONS = 100_000


def hash_password(password: str):
    """Returns (salt_hex, hash_hex) for a new password."""
    salt = secrets.token_bytes(16)
    hashed = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return salt.hex(), hashed.hex()


def verify_password(password: str, salt_hex: str, hash_hex: str) -> bool:
    salt = bytes.fromhex(salt_hex)
    hashed = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return hashed.hex() == hash_hex