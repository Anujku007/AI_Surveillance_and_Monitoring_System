"""
live_feed.py
Runs the camera capture + detection + tracking loop in a background thread,
so it can feed an embedded Tkinter video widget without freezing the UI.

This reuses the same drawing/alert logic as main.py's standalone window —
the only difference is frames are handed off to the GUI instead of shown
via cv2.imshow().

Usage:
    controller = LiveFeedController()
    controller.start()
    frame = controller.get_latest_frame()   # BGR numpy array, or None
    stats = controller.get_stats()
    controller.stop()
"""

import threading
import time
import cv2

from config import CAMERA_INDEX, PROCESS_EVERY_N_FRAMES, ALERT_COOLDOWN_SECONDS
from error_handler import logger
from detector import FaceDetector
from encoder import FaceEncoder
from tracker import EntryExitTracker
from database import get_all_persons
from main import draw_results, draw_overlay_bar, play_alert


class LiveFeedController:
    def __init__(self, camera_source=None, camera_name="Main Entrance"):
        self.camera_source = camera_source if camera_source is not None else CAMERA_INDEX
        self.camera_name = camera_name

        self.detector = None
        self.encoder = None
        self.tracker = None
        self.cap = None
        self.thread = None
        self.running = False

        self._lock = threading.Lock()
        self._latest_frame = None
        self._stats = {"fps": 0.0, "faces": 0, "known": 0, "unknown": 0, "spoof": 0, "repeat": 0}

    def is_running(self):
        return self.running

    def start(self):
        if self.running:
            return True

        try:
            self.detector = FaceDetector()
        except Exception as e:
            logger.error(f"Could not start live feed ({self.camera_name}) — model load failed: {e}")
            return False

        self.encoder = FaceEncoder(get_all_persons())
        self.tracker = EntryExitTracker(camera_location=self.camera_name)

        self.cap = cv2.VideoCapture(self.camera_source)
        if not self.cap.isOpened():
            logger.error(f"Could not open camera '{self.camera_name}' (source={self.camera_source}).")
            self.cap = None
            return False

        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        logger.info(f"Live feed started: {self.camera_name}")
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
            self._latest_frame = None
        logger.info(f"Live feed stopped: {self.camera_name}")

    def refresh_known_persons(self):
        """Call after registering a new person so recognition picks them up immediately."""
        if self.encoder:
            self.encoder.refresh_known_persons(get_all_persons())

    def get_latest_frame(self):
        with self._lock:
            return None if self._latest_frame is None else self._latest_frame.copy()

    def get_stats(self):
        with self._lock:
            return dict(self._stats)

    def _loop(self):
        frame_count = 0
        last_results = []
        fps = 0.0
        fps_last_time = time.time()
        fps_frame_counter = 0
        last_alert_time = 0

        while self.running:
            ret, frame = self.cap.read()
            if not ret:
                time.sleep(0.1)
                continue

            frame_count += 1
            fps_frame_counter += 1
            now = time.time()
            if now - fps_last_time >= 1.0:
                fps = fps_frame_counter / (now - fps_last_time)
                fps_frame_counter = 0
                fps_last_time = now

            if frame_count % PROCESS_EVERY_N_FRAMES == 0:
                try:
                    boxes = self.detector.detect(frame)
                    results = self.encoder.recognize(frame, boxes)
                    last_results = results
                    self.tracker.update(results, frame)
                except Exception as e:
                    logger.warning(f"Live feed processing error: {e}")

            display_frame, known, unknown, spoof, repeat = draw_results(frame.copy(), last_results)
            display_frame = draw_overlay_bar(display_frame, fps, len(last_results), known, unknown)

            if (unknown > 0 or spoof > 0 or repeat > 0) and (now - last_alert_time) >= ALERT_COOLDOWN_SECONDS:
                play_alert()
                last_alert_time = now

            with self._lock:
                self._latest_frame = display_frame
                self._stats = {"fps": fps, "faces": len(last_results), "known": known,
                                "unknown": unknown, "spoof": spoof, "repeat": repeat}