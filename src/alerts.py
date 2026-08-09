"""
alerts.py
Sends email alerts for suspicious detections (unknown face, spoof suspected,
repeat offender), using Gmail SMTP with an app password.

Setup (one-time):
    1. Enable 2-Step Verification on the sending Gmail account.
    2. Generate an App Password: Google Account -> Security -> App Passwords.
    3. Run this file directly to be prompted and save the config:
           python alerts.py --setup

Credentials are stored in database/email_config.json (NOT in config.py or
git), so real credentials never end up in source control.

Usage:
    from alerts import send_alert_email_async
    send_alert_email_async("Unknown Face Detected", "...", snapshot_path)
"""

import os
import json
import time
import smtplib
import threading
from email.message import EmailMessage

from config import EMAIL_CONFIG_PATH, EMAIL_ALERT_COOLDOWN_SECONDS
from error_handler import logger

_last_sent_time = 0
_lock = threading.Lock()


def is_email_configured():
    return os.path.exists(EMAIL_CONFIG_PATH)


def load_email_config():
    if not is_email_configured():
        return None
    with open(EMAIL_CONFIG_PATH) as f:
        return json.load(f)


def save_email_config(sender_email, app_password, recipient_email, enabled=True):
    config = {
        "sender_email": sender_email,
        "app_password": app_password,
        "recipient_email": recipient_email,
        "enabled": enabled,
    }
    with open(EMAIL_CONFIG_PATH, "w") as f:
        json.dump(config, f)
    logger.info("Email alert configuration saved.")


def _send_email_sync(subject, body, snapshot_path=None):
    config = load_email_config()
    if not config or not config.get("enabled"):
        return

    global _last_sent_time
    with _lock:
        now = time.time()
        if now - _last_sent_time < EMAIL_ALERT_COOLDOWN_SECONDS:
            return  # cooldown active, skip this alert
        _last_sent_time = now

    try:
        msg = EmailMessage()
        msg["Subject"] = f"[AI Surveillance Alert] {subject}"
        msg["From"] = config["sender_email"]
        msg["To"] = config["recipient_email"]
        msg.set_content(body)

        if snapshot_path and os.path.exists(snapshot_path):
            with open(snapshot_path, "rb") as f:
                msg.add_attachment(f.read(), maintype="image", subtype="jpeg",
                                    filename=os.path.basename(snapshot_path))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(config["sender_email"], config["app_password"])
            server.send_message(msg)

        logger.info(f"Alert email sent: {subject}")
    except Exception as e:
        logger.warning(f"Could not send alert email: {e}")


def send_alert_email_async(subject, body, snapshot_path=None):
    """Sends the email in a background thread so the camera loop never blocks
    waiting on a slow/failed SMTP connection."""
    if not is_email_configured():
        return
    threading.Thread(
        target=_send_email_sync, args=(subject, body, snapshot_path), daemon=True
    ).start()


if __name__ == "__main__":
    import sys
    if "--setup" in sys.argv:
        print("=== Email Alert Setup ===")
        print("Requires a Gmail App Password (not your normal password).")
        print("Generate one at: Google Account -> Security -> App Passwords\n")
        sender = input("Sender Gmail address: ").strip()
        app_pw = input("App Password (16 characters, no spaces): ").strip().replace(" ", "")
        recipient = input("Recipient email (can be the same address): ").strip()
        save_email_config(sender, app_pw, recipient, enabled=True)
        print("Saved. Sending a test email...")
        _send_email_sync("Test Alert", "This is a test alert from your AI Surveillance System setup.")
        print("Done — check your inbox (and spam folder).")
    else:
        print("Run with --setup to configure email alerts:")
        print("    python alerts.py --setup")