"""
crypto.py
Encrypts/decrypts sensitive biometric data (face embeddings) before they
are stored in or read from the database, using symmetric (Fernet) encryption.

The encryption key is auto-generated on first run and saved to
database/secret.key. This file is the ONLY thing that can decrypt stored
face data — treat it like a password:
    - Never commit it to git (add it to .gitignore)
    - Back it up separately from the database itself
    - If it's lost, all previously registered faces become unreadable and
      must be re-registered

Usage:
    from crypto import encrypt_bytes, decrypt_bytes

    encrypted = encrypt_bytes(embedding.tobytes())
    original = decrypt_bytes(encrypted)
"""

import os
from cryptography.fernet import Fernet, InvalidToken

from config import ENCRYPTION_KEY_PATH
from error_handler import logger


def _load_or_create_key():
    if os.path.exists(ENCRYPTION_KEY_PATH):
        with open(ENCRYPTION_KEY_PATH, "rb") as f:
            return f.read()

    key = Fernet.generate_key()
    with open(ENCRYPTION_KEY_PATH, "wb") as f:
        f.write(key)
    logger.info(f"Generated new encryption key at {ENCRYPTION_KEY_PATH}")
    return key


_key = _load_or_create_key()
_fernet = Fernet(_key)


def encrypt_bytes(data: bytes) -> bytes:
    """Encrypts raw bytes (e.g. a face embedding) before storing in the DB."""
    return _fernet.encrypt(data)


def decrypt_bytes(data: bytes) -> bytes:
    """
    Decrypts bytes previously encrypted with encrypt_bytes().
    Raises a clear error if the data can't be decrypted (wrong key, or
    the data was never encrypted in the first place — e.g. leftover
    plaintext rows from before encryption was added).
    """
    try:
        return _fernet.decrypt(data)
    except InvalidToken:
        raise ValueError(
            "Could not decrypt stored data — this usually means the "
            "encryption key changed, or this record predates encryption "
            "being enabled. Affected persons/entries need to be re-registered."
        )