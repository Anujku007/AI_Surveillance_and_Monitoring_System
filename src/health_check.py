"""
health_check.py
Runs a startup self-test of the system's critical components — camera,
face detection model, database, and encryption — and reports a clean
pass/fail checklist before the app goes live.

Usage:
    from health_check import run_health_check, print_health_report

    results = run_health_check()
    print_health_report(results)
"""

import os
import cv2

from config import PROTOTXT_PATH, CAFFEMODEL_PATH, CAMERAS, DB_PATH, ENCRYPTION_KEY_PATH
from error_handler import logger


def _check(name, fn):
    try:
        ok, detail = fn()
        return {"name": name, "ok": ok, "detail": detail}
    except Exception as e:
        return {"name": name, "ok": False, "detail": str(e)}


def check_models():
    if not os.path.exists(PROTOTXT_PATH) or not os.path.exists(CAFFEMODEL_PATH):
        return False, "Model files missing from models/ — see setup instructions."
    net = cv2.dnn.readNetFromCaffe(PROTOTXT_PATH, CAFFEMODEL_PATH)
    if net is None:
        return False, "Model files found but failed to load."
    return True, "Face detection model loaded successfully."


def check_cameras():
    results = []
    any_ok = False
    for cam in CAMERAS:
        cap = cv2.VideoCapture(cam["source"])
        opened = cap.isOpened()
        if opened:
            ret, _ = cap.read()
            opened = opened and ret
        cap.release()
        results.append(f"{cam['name']}: {'OK' if opened else 'not reachable'}")
        any_ok = any_ok or opened
    detail = "; ".join(results) if results else "No cameras configured."
    return any_ok, detail


def check_database():
    from database import init_db, get_all_persons
    from config import DB_BACKEND
    init_db()
    persons = get_all_persons()
    return True, f"Database OK (backend: {DB_BACKEND}) — {len(persons)} registered person(s)."


def check_encryption():
    from crypto import encrypt_bytes, decrypt_bytes
    if not os.path.exists(ENCRYPTION_KEY_PATH):
        return False, "Encryption key not found — will be auto-generated on first use."
    test = b"health-check-roundtrip"
    if decrypt_bytes(encrypt_bytes(test)) != test:
        return False, "Encryption round-trip failed."
    return True, "Encryption key present and working."


def check_admin_auth():
    from auth import is_password_set
    if is_password_set():
        return True, "Admin password is set."
    return True, "No admin password set yet — first-run setup will prompt for one."


def check_email_alerts():
    from alerts import is_email_configured
    if is_email_configured():
        return True, "Email alerts configured."
    return True, "Email alerts not configured (optional) — run 'python alerts.py --setup' to enable."


def run_health_check():
    """Returns a list of check result dicts: {name, ok, detail}."""
    return [
        _check("Face Detection Model", check_models),
        _check("Camera(s)", check_cameras),
        _check("Database", check_database),
        _check("Encryption", check_encryption),
        _check("Admin Authentication", check_admin_auth),
        _check("Email Alerts (optional)", check_email_alerts),
    ]


def print_health_report(results):
    logger.info("=" * 50)
    logger.info("SYSTEM HEALTH CHECK")
    logger.info("=" * 50)
    for r in results:
        status = "PASS" if r["ok"] else "FAIL"
        logger.info(f"[{status}] {r['name']}: {r['detail']}")
    logger.info("=" * 50)

    critical = results[:4]  # model, camera, database, encryption
    if all(r["ok"] for r in critical):
        logger.info("All critical checks passed. System ready.")
    else:
        logger.warning("One or more critical checks failed — see above. The app will still start.")


if __name__ == "__main__":
    print_health_report(run_health_check())