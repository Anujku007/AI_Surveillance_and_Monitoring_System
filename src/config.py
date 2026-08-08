"""
config.py
Centralized configuration for the AI Surveillance System.
Keep all tunable values here so they can be adjusted in one place
(and referenced/justified easily in the project report/viva).
"""

import os

# ---------------------------------------------------------
# Base paths
# ---------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

MODELS_DIR = os.path.join(BASE_DIR, "models")
DATABASE_DIR = os.path.join(BASE_DIR, "database")
KNOWN_FACES_DIR = os.path.join(DATABASE_DIR, "known_faces")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
SNAPSHOTS_DIR = os.path.join(LOGS_DIR, "snapshots")

DB_PATH = os.path.join(DATABASE_DIR, "surveillance.db")

# Encryption key for biometric data (face embeddings). Auto-generated on
# first run if it doesn't exist — see crypto.py. Keep this file private;
# anyone with it can decrypt stored face data. Do not commit it to git.
ENCRYPTION_KEY_PATH = os.path.join(DATABASE_DIR, "secret.key")

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
# Entry/Exit tracking logic
# ---------------------------------------------------------
# How many seconds a person must be absent from frame before
# we consider them "exited" (avoids false exits from brief occlusion)
EXIT_TIMEOUT_SECONDS = 5

# Minimum gap between two log entries for the SAME person,
# to prevent duplicate ENTRY/EXIT spam from flickering detections
LOG_COOLDOWN_SECONDS = 10

# ---------------------------------------------------------
# Display settings
# ---------------------------------------------------------
COLOR_KNOWN = (0, 255, 0)     # green (BGR) for recognized/authorized person
COLOR_UNKNOWN = (0, 0, 255)   # red (BGR) for unrecognized/suspicious person
COLOR_SPOOF = (0, 140, 255)   # orange (BGR) for suspected photo/video spoof
COLOR_REPEAT = (255, 0, 200)  # magenta (BGR) for repeat-offender unknown visitor
BOX_THICKNESS = 2
FONT = "FONT_HERSHEY_SIMPLEX"
FONT_SCALE = 0.6

# ---------------------------------------------------------
# Alert sound settings
# ---------------------------------------------------------
ENABLE_ALERT_SOUND = True
ALERT_COOLDOWN_SECONDS = 5   # minimum gap between alert sounds, avoids spamming

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