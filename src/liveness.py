"""
liveness.py
Blink-based liveness detection (anti-spoofing).

A static photo or video played on a screen won't blink like a real person.
By tracking the Eye Aspect Ratio (EAR) across frames, we can detect genuine
blinks and use their presence (or absence) as a signal that a face belongs
to a real, live person rather than a photo/video held up to the camera.

Reference technique: Soukupová & Čech, "Real-Time Eye Blink Detection using
Facial Landmarks" (2016) — EAR drops sharply when the eye closes.

Usage:
    from liveness import LivenessChecker

    checker = LivenessChecker()
    checker.update(key, landmarks, time.time())
    checker.has_blinked(key)          -> bool
    checker.is_spoof_suspected(key, time.time())  -> bool
"""

import numpy as np

from config import (
    LIVENESS_EAR_THRESHOLD, LIVENESS_CONSEC_FRAMES, LIVENESS_TIMEOUT_SECONDS
)


def _euclidean(p1, p2):
    return np.linalg.norm(np.array(p1) - np.array(p2))


def eye_aspect_ratio(eye_points):
    """
    Computes the Eye Aspect Ratio (EAR) for a single eye.
    `eye_points` must be 6 (x, y) points, as returned by
    face_recognition.face_landmarks()['left_eye'] / ['right_eye'].

    EAR stays roughly constant while the eye is open, and drops sharply
    (close to 0) when the eye closes during a blink.
    """
    if len(eye_points) < 6:
        return None

    vertical_1 = _euclidean(eye_points[1], eye_points[5])
    vertical_2 = _euclidean(eye_points[2], eye_points[4])
    horizontal = _euclidean(eye_points[0], eye_points[3])

    if horizontal == 0:
        return None

    return (vertical_1 + vertical_2) / (2.0 * horizontal)


def average_ear_from_landmarks(landmarks):
    """
    Given a face_recognition landmarks dict, returns the average EAR of
    both eyes, or None if eye landmarks aren't available for this face.
    """
    if not landmarks:
        return None

    left_eye = landmarks.get("left_eye")
    right_eye = landmarks.get("right_eye")
    if not left_eye or not right_eye:
        return None

    left_ear = eye_aspect_ratio(left_eye)
    right_ear = eye_aspect_ratio(right_eye)

    if left_ear is None or right_ear is None:
        return None

    return (left_ear + right_ear) / 2.0


class LivenessChecker:
    """
    Tracks blink state per tracking key (a registered person_id, or a
    temporary unknown-face ID from tracker.UnknownFaceRegistry).
    """
    def __init__(self):
        # key -> {"consec_below": int, "blinked": bool, "first_seen": ts}
        self.state = {}

    def update(self, key, landmarks, now):
        """Call once per processed frame for each visible face."""
        ear = average_ear_from_landmarks(landmarks)

        st = self.state.setdefault(key, {
            "consec_below": 0,
            "blinked": False,
            "first_seen": now,
        })

        if ear is None:
            # Couldn't compute EAR this frame (bad angle, partial occlusion,
            # etc.) — don't penalize, just skip this frame's update.
            return

        if ear < LIVENESS_EAR_THRESHOLD:
            st["consec_below"] += 1
        else:
            if st["consec_below"] >= LIVENESS_CONSEC_FRAMES:
                st["blinked"] = True
            st["consec_below"] = 0

    def has_blinked(self, key):
        st = self.state.get(key)
        return bool(st and st["blinked"])

    def is_spoof_suspected(self, key, now):
        """
        True if this face has been tracked long enough (LIVENESS_TIMEOUT_SECONDS)
        without a single detected blink — a strong signal it's a static
        photo/video rather than a live person.
        """
        st = self.state.get(key)
        if not st:
            return False
        if st["blinked"]:
            return False
        return (now - st["first_seen"]) >= LIVENESS_TIMEOUT_SECONDS

    def forget(self, key):
        """Clears tracking state for a key (call when a person exits, so a
        fresh liveness check starts if/when they reappear)."""
        self.state.pop(key, None)