"""
registration_panel.py
Lightweight camera controller used only for the "Register Person" tab's
live preview — separate from live_feed.py's full detection/tracking loop,
since registration just needs "how many faces, draw a guide box" without
recognition or entry/exit logic.
"""

import threading
import time
import cv2

from config import CAMERA_INDEX, COLOR_KNOWN, COLOR_UNKNOWN
from error_handler import logger
from detector import FaceDetector


class RegistrationCamera:
    def __init__(self):
        self.detector = None
        self.cap = None
        self.running = False
        self.thread = None

        self._lock = threading.Lock()
        self._latest_preview = None   # annotated frame, for display
        self._latest_raw = None       # raw frame, for actual capture/encoding
        self._face_count = 0

    def start(self):
        if self.running:
            return True
        try:
            self.detector = FaceDetector()
        except Exception as e:
            logger.error(f"Could not start registration camera — model load failed: {e}")
            return False

        self.cap = cv2.VideoCapture(CAMERA_INDEX)
        if not self.cap.isOpened():
            logger.error("Could not open webcam for registration preview.")
            self.cap = None
            return False

        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        return True

    def stop(self):
        if not self.running:
            return
        self.running = False
        if self.thread:
            self.thread.join(timeout=2)
        if self.cap:
            self.cap.release()
            self.cap = None
        with self._lock:
            self._latest_preview = None
            self._latest_raw = None
            self._face_count = 0

    def get_preview_frame(self):
        with self._lock:
            return None if self._latest_preview is None else self._latest_preview.copy()

    def get_face_count(self):
        with self._lock:
            return self._face_count

    def capture_raw_frame(self):
        """Returns the current unannotated frame, for actual registration. None if unavailable."""
        with self._lock:
            return None if self._latest_raw is None else self._latest_raw.copy()

    def _loop(self):
        while self.running:
            ret, frame = self.cap.read()
            if not ret:
                time.sleep(0.1)
                continue

            boxes = self.detector.detect(frame)
            display = frame.copy()
            color = COLOR_KNOWN if len(boxes) == 1 else COLOR_UNKNOWN
            for (top, right, bottom, left) in boxes:
                cv2.rectangle(display, (left, top), (right, bottom), color, 2)

            with self._lock:
                self._latest_preview = display
                self._latest_raw = frame
                self._face_count = len(boxes)