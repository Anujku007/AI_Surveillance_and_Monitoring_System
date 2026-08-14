"""
config.py
Centralized configuration for the AI Surveillance System.
Keep all tunable values here so they can be adjusted in one place
(and referenced/justified easily in the project report/viva).
"""

import os
import json
import json

# ---------------------------------------------------------
# Base paths
# ---------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

MODELS_DIR = os.path.join(BASE_DIR, "models")
DATABASE_DIR = os.path.join(BASE_DIR, "database")
KNOWN_FACES_DIR = os.path.join(DATABASE_DIR, "known_faces")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
SNAPSHOTS_DIR = os.path.join(LOGS_DIR, "snapshots")

# ---------------------------------------------------------
# Environment variables (.env) — loaded here, first, since config.py is
# always the first module imported by any entry point. This guarantees
# env vars (DB backend choice, Postgres credentials, Flask secret key)
# are available before anything else in the app runs.
# ---------------------------------------------------------
os.makedirs(DATABASE_DIR, exist_ok=True)
ENV_PATH = os.path.join(DATABASE_DIR, ".env")
if not os.path.exists(ENV_PATH):
    import secrets as _secrets
    with open(ENV_PATH, "w") as f:
        f.write(f"FLASK_SECRET_KEY={_secrets.token_hex(32)}\n")
        f.write("DB_BACKEND=sqlite\n")
        f.write("# Uncomment and fill in to use PostgreSQL instead of SQLite:\n")
        f.write("# DB_BACKEND=postgresql\n")
        f.write("# POSTGRES_HOST=localhost\n")
        f.write("# POSTGRES_PORT=5432\n")
        f.write("# POSTGRES_DB=surveillance\n")
        f.write("# POSTGRES_USER=postgres\n")
        f.write("# POSTGRES_PASSWORD=change-me\n")

from dotenv import load_dotenv
load_dotenv(ENV_PATH)

DB_PATH = os.path.join(DATABASE_DIR, "surveillance.db")

# Load database/.env as early as possible — config.py is always the first
# module imported by everything else, so this must happen here (not in
# web_app.py) for DB_BACKEND/PG_* below to see values from the .env file.
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(DATABASE_DIR, ".env"))
except ImportError:
    pass  # python-dotenv not installed yet — env vars just won't be loaded from file

# ---------------------------------------------------------
# Database backend
# ---------------------------------------------------------
# "sqlite" (default, zero setup — local development / single-machine demo)
# or "postgresql" (production-grade, safely handles concurrent writes from
# multiple cameras/sites — the realistic choice for a real deployment).
# Set via DB_BACKEND in database/.env. Requires an app restart to apply.
DB_BACKEND = os.environ.get("DB_BACKEND", "sqlite")

# Only used when DB_BACKEND=postgresql. Set these in database/.env —
# never hardcode real credentials here, this file may end up in a report
# or version control.
PG_HOST = os.environ.get("PG_HOST", "localhost")
PG_PORT = os.environ.get("PG_PORT", "5432")
PG_DBNAME = os.environ.get("PG_DBNAME", "surveillance")
PG_USER = os.environ.get("PG_USER", "postgres")
PG_PASSWORD = os.environ.get("PG_PASSWORD", "")

# ---------------------------------------------------------
# Database backend
# ---------------------------------------------------------
# 'sqlite' — local/single-site use (default, zero setup, what the desktop
#            and development workflow use).
# 'postgresql' — production/multi-site deployment. Requires a running
#            PostgreSQL server and psycopg2-binary installed. Set via
#            database/.env — never hardcode real credentials in this file.
DB_BACKEND = os.environ.get("DB_BACKEND", "sqlite").strip().lower()

POSTGRES_CONFIG = {
    "host": os.environ.get("POSTGRES_HOST", "localhost"),
    "port": int(os.environ.get("POSTGRES_PORT", 5432)),
    "dbname": os.environ.get("POSTGRES_DB", "surveillance"),
    "user": os.environ.get("POSTGRES_USER", "postgres"),
    "password": os.environ.get("POSTGRES_PASSWORD", ""),
}

# Encryption key for biometric data (face embeddings). Auto-generated on
# first run if it doesn't exist — see crypto.py. Keep this file private;
# anyone with it can decrypt stored face data. Do not commit it to git.
ENCRYPTION_KEY_PATH = os.path.join(DATABASE_DIR, "secret.key")

# ---------------------------------------------------------
# Email alerts
# ---------------------------------------------------------
# Credentials live in a separate JSON file (NOT this file), same pattern
# as secret.key — so real credentials never end up in source control or
# get pasted into a report. See alerts.py for the setup helper.
EMAIL_CONFIG_PATH = os.path.join(DATABASE_DIR, "email_config.json")

# Minimum gap between two alert emails, regardless of how many suspicious
# events occur — protects against flooding your inbox during testing or
# a burst of detections.
EMAIL_ALERT_COOLDOWN_SECONDS = 30

# ---------------------------------------------------------
# DNN face detector model files (OpenCV)
# ---------------------------------------------------------
PROTOTXT_PATH = os.path.join(MODELS_DIR, "deploy.prototxt")
CAFFEMODEL_PATH = os.path.join(MODELS_DIR, "res10_300x300_ssd_iter_140000.caffemodel")

# Minimum confidence for a detection box to be considered a real face
DETECTION_CONFIDENCE_THRESHOLD = 0.5

# ---------------------------------------------------------
# Face recognition (encoding/comparison) settings
# ---------------------------------------------------------
# Lower = stricter matching (fewer false matches, more false "unknowns")
# Higher = looser matching (more false matches, fewer false "unknowns")
# 0.6 is the face_recognition library's own recommended default — tune
# based on testing with your actual registered faces.
FACE_MATCH_TOLERANCE = 0.6

# Tolerance used ONLY to tell two unrecognized (unknown) faces apart from
# each other across frames, so multiple strangers get separate temporary
# tracking IDs instead of colliding into one shared "unknown" bucket.
# NOTE: 0.5 was found too strict in testing — normal frame-to-frame
# variation (angle, lighting) could split one real stranger into multiple
# temp IDs. 0.58 gives more headroom while still being tighter than the
# 0.6 used for registered-person matching (since we'd rather slightly
# under-split strangers than falsely merge two different people).
UNKNOWN_FACE_MATCH_TOLERANCE = 0.58

# How long an unknown face's temporary tracking ID is kept alive after
# they leave the frame, before it's discarded (if they return after this,
# they'll be assigned a new temp ID — a known limitation, not a bug)
UNKNOWN_ID_EXPIRY_SECONDS = 15

# ---------------------------------------------------------
# Repeat-offender watchlist (persists across sessions/days)
# ---------------------------------------------------------
# Same distance tolerance as above, reused for matching against the
# persistent watchlist stored in the database (separate from the
# in-memory per-session UnknownFaceRegistry).
REPEAT_OFFENDER_MATCH_TOLERANCE = 0.58

# Number of separate sightings (across different sessions/visits) before
# an unknown face gets escalated from "Unknown Face" to "Repeat Offender"
REPEAT_OFFENDER_THRESHOLD = 3

# ---------------------------------------------------------
# Camera settings
# ---------------------------------------------------------
CAMERA_INDEX = 0          # 0 = default laptop webcam
FRAME_WIDTH = 640
FRAME_HEIGHT = 480
PROCESS_EVERY_N_FRAMES = 3   # skip frames to keep real-time performance

# ---------------------------------------------------------
# Multi-camera support
# ---------------------------------------------------------
# Each entry: id (used internally/in URLs), name (shown in UI and saved as
# camera_location in logs), source (int index for a local webcam, or a URL
# string for an IP camera / phone camera app, e.g. the Android "IP Webcam"
# app's MJPEG URL). cv2.VideoCapture() accepts both transparently.
CAMERAS = [
    {"id": "cam1", "name": "Main Entrance", "source": CAMERA_INDEX},
    # Add more cameras here, for example a phone running the "IP Webcam"
    # Android app on the same network:
    # {"id": "cam2", "name": "Back Entrance", "source": "http://192.168.1.5:8080/video"},
]

# ---------------------------------------------------------
# Camera auto-recovery
# ---------------------------------------------------------
# If this many consecutive frame reads fail, the camera is considered
# disconnected and a reconnect attempt is triggered.
CAMERA_READ_FAIL_THRESHOLD = 15

# Reconnect attempts back off exponentially between these bounds (seconds),
# so a genuinely unplugged camera doesn't spin retrying every few ms.
CAMERA_RECONNECT_BASE_DELAY = 1
CAMERA_RECONNECT_MAX_DELAY = 15

# ---------------------------------------------------------
# Camera auto-recovery
# ---------------------------------------------------------
# Consecutive failed frame reads before a camera is considered disconnected
# (rather than reacting to a single dropped frame, which is normal/harmless)
CAMERA_FAILURE_THRESHOLD = 15

# Reconnect attempts back off exponentially between these bounds, so a
# genuinely unplugged camera doesn't get hammered with retry attempts
CAMERA_RECONNECT_INITIAL_DELAY = 1
CAMERA_RECONNECT_MAX_DELAY = 15

# ---------------------------------------------------------
# Entry/Exit tracking logic
# ---------------------------------------------------------
# How many seconds a person must be absent from frame before
# we consider them "exited" (avoids false exits from brief occlusion)
EXIT_TIMEOUT_SECONDS = 5

# Minimum gap between two log entries for the SAME person,
# to prevent duplicate ENTRY/EXIT spam from flickering detections
LOG_COOLDOWN_SECONDS = 10

# ---------------------------------------------------------
# Confidence-based re-verification
# ---------------------------------------------------------
# Instead of logging ENTRY the instant a face is first seen, require the
# same identity decision (matched to person X, or unmatched) to repeat for
# this many consecutive PROCESSED frames first. Prevents a single noisy/
# bad-angle frame from triggering a premature or incorrect log entry.
CONFIDENCE_MIN_FRAMES = 3

# ---------------------------------------------------------
# Display settings
# ---------------------------------------------------------
COLOR_KNOWN = (0, 255, 0)     # green (BGR) for recognized/authorized person
COLOR_UNKNOWN = (0, 0, 255)   # red (BGR) for unrecognized/suspicious person
COLOR_SPOOF = (0, 140, 255)   # orange (BGR) for suspected photo/video spoof
COLOR_REPEAT = (255, 0, 200)  # magenta (BGR) for repeat-offender unknown visitor
COLOR_VERIFYING = (180, 180, 180)  # gray (BGR) — identity not yet confirmed
BOX_THICKNESS = 2
FONT = "FONT_HERSHEY_SIMPLEX"
FONT_SCALE = 0.6

# ---------------------------------------------------------
# Alert sound settings
# ---------------------------------------------------------
ENABLE_ALERT_SOUND = True
ALERT_COOLDOWN_SECONDS = 5   # minimum gap between alert sounds, avoids spamming

# ---------------------------------------------------------
# HTTPS (self-signed, for local demo/testing)
# ---------------------------------------------------------
# When True, the web app serves over HTTPS using an auto-generated
# self-signed certificate (requires pyOpenSSL). Browsers will show a
# security warning since it's self-signed, not from a trusted CA — expected
# for local development. Set to False to run plain HTTP (e.g. if pyOpenSSL
# isn't installed, or during quick local testing).
# ---------------------------------------------------------
# Data retention
# ---------------------------------------------------------
# Entry/exit logs, snapshots, and stale watchlist entries older than this
# many days are purged automatically at startup and can also be purged
# manually from the Settings page. Set to 0 to disable auto-purge.
RETENTION_DAYS = 90

ENABLE_HTTPS = False

# ---------------------------------------------------------
# Liveness detection (anti-spoofing via blink detection)
# ---------------------------------------------------------
ENABLE_LIVENESS_CHECK = True

# EAR (Eye Aspect Ratio) drops sharply during a blink. Below this value,
# the eye is considered "closed" for that frame. 0.21 is a commonly used
# starting point — tune based on your own webcam/lighting during testing.
LIVENESS_EAR_THRESHOLD = 0.21

# Number of consecutive low-EAR frames required to count as a real blink
# (filters out single-frame noise from detection jitter)
LIVENESS_CONSEC_FRAMES = 2

# If a face has been visible this long with NO blink detected yet,
# it gets flagged as "spoof suspected" (e.g. a printed photo held up
# to the camera, or a photo/video played on a phone screen)
LIVENESS_TIMEOUT_SECONDS = 8

# ---------------------------------------------------------
# Ensure required directories exist at import time
# ---------------------------------------------------------
for directory in (MODELS_DIR, DATABASE_DIR, KNOWN_FACES_DIR, LOGS_DIR, SNAPSHOTS_DIR):
    os.makedirs(directory, exist_ok=True)

# ---------------------------------------------------------
# Runtime-configurable settings (settings.json) — lets an admin adjust
# these values through the web UI's Settings page instead of editing this
# file directly. Changes take effect after the app is restarted, since
# Python module values are fixed at import time.
# ---------------------------------------------------------
SETTINGS_PATH = os.path.join(DATABASE_DIR, "settings.json")

TUNABLE_SETTINGS = {
    "FACE_MATCH_TOLERANCE": FACE_MATCH_TOLERANCE,
    "EXIT_TIMEOUT_SECONDS": EXIT_TIMEOUT_SECONDS,
    "LOG_COOLDOWN_SECONDS": LOG_COOLDOWN_SECONDS,
    "PROCESS_EVERY_N_FRAMES": PROCESS_EVERY_N_FRAMES,
    "ENABLE_LIVENESS_CHECK": ENABLE_LIVENESS_CHECK,
    "LIVENESS_EAR_THRESHOLD": LIVENESS_EAR_THRESHOLD,
    "LIVENESS_TIMEOUT_SECONDS": LIVENESS_TIMEOUT_SECONDS,
    "REPEAT_OFFENDER_THRESHOLD": REPEAT_OFFENDER_THRESHOLD,
    "ENABLE_ALERT_SOUND": ENABLE_ALERT_SOUND,
    "ALERT_COOLDOWN_SECONDS": ALERT_COOLDOWN_SECONDS,
    "RETENTION_DAYS": RETENTION_DAYS,
}


def _load_settings_overrides():
    if not os.path.exists(SETTINGS_PATH):
        return
    try:
        with open(SETTINGS_PATH) as f:
            saved = json.load(f)
        for key, value in saved.items():
            if key == "CAMERAS":
                globals()["CAMERAS"] = value
            elif key in TUNABLE_SETTINGS:
                globals()[key] = value
                TUNABLE_SETTINGS[key] = value
    except Exception:
        pass  # fall back silently to defaults — error_handler isn't available this early


def get_current_settings():
    settings = dict(TUNABLE_SETTINGS)
    settings["CAMERAS"] = CAMERAS
    return settings


def save_settings(new_values):
    current = get_current_settings()
    current.update(new_values)
    with open(SETTINGS_PATH, "w") as f:
        json.dump(current, f, indent=2)


_load_settings_overrides()

# ---------------------------------------------------------
# Runtime-configurable settings (settings.json overrides)
# ---------------------------------------------------------
# Lets the Settings tab in the web app tune these values without editing
# this file directly. Changes are saved to settings.json and take effect
# on the NEXT restart (values below are already imported by other modules
# at import time, so this is not a live/hot-reload).
SETTINGS_PATH = os.path.join(DATABASE_DIR, "settings.json")

EDITABLE_SETTINGS_KEYS = [
    "CAMERAS",
    "DETECTION_CONFIDENCE_THRESHOLD",
    "FACE_MATCH_TOLERANCE",
    "PROCESS_EVERY_N_FRAMES",
    "EXIT_TIMEOUT_SECONDS",
    "LOG_COOLDOWN_SECONDS",
    "CONFIDENCE_MIN_FRAMES",
    "ENABLE_LIVENESS_CHECK",
    "LIVENESS_EAR_THRESHOLD",
    "LIVENESS_TIMEOUT_SECONDS",
    "REPEAT_OFFENDER_THRESHOLD",
    "ENABLE_ALERT_SOUND",
    "ALERT_COOLDOWN_SECONDS",
    "EMAIL_ALERT_COOLDOWN_SECONDS",
]


def _load_settings_overrides():
    if not os.path.exists(SETTINGS_PATH):
        return
    try:
        with open(SETTINGS_PATH) as f:
            overrides = json.load(f)
        for key, value in overrides.items():
            if key in EDITABLE_SETTINGS_KEYS:
                globals()[key] = value
    except Exception as e:
        print(f"Warning: could not load settings.json overrides: {e}")


_load_settings_overrides()


def get_current_settings():
    """Returns current values of all editable settings — for the Settings UI."""
    return {key: globals()[key] for key in EDITABLE_SETTINGS_KEYS}


def save_settings(new_values):
    """
    Persists the given key/value pairs to settings.json (merged with any
    existing overrides). Only keys in EDITABLE_SETTINGS_KEYS are accepted.
    Takes effect on the next app restart.
    """
    current = {}
    if os.path.exists(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH) as f:
                current = json.load(f)
        except Exception:
            current = {}

    for key, value in new_values.items():
        if key in EDITABLE_SETTINGS_KEYS:
            current[key] = value

    with open(SETTINGS_PATH, "w") as f:
        json.dump(current, f, indent=2)