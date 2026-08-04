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
BOX_THICKNESS = 2
FONT = "FONT_HERSHEY_SIMPLEX"
FONT_SCALE = 0.6

# ---------------------------------------------------------
# Ensure required directories exist at import time
# ---------------------------------------------------------
for directory in (MODELS_DIR, DATABASE_DIR, KNOWN_FACES_DIR, LOGS_DIR, SNAPSHOTS_DIR):
    os.makedirs(directory, exist_ok=True)