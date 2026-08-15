"""
tracker.py
Entry/Exit state machine for the AI Surveillance System.

Since a single camera has no inherent sense of "direction," this module
infers ENTRY/EXIT purely from presence over time:
    - A person who was absent and is now detected  -> ENTRY
    - A person who was present and is now absent
      for longer than EXIT_TIMEOUT_SECONDS          -> EXIT

Registered persons are tracked individually by their database person_id.
Unknown (unregistered) faces are tracked using temporary in-memory IDs,
assigned by comparing face embeddings frame-to-frame via UnknownFaceRegistry
below — this lets multiple different strangers be tracked as separate
people during a single session, instead of colliding into one shared
"unknown" bucket. These temp IDs are NOT saved to the database — they only
exist in memory to keep ENTRY/EXIT logic correct while people are on camera.

On top of that, each unknown ENTRY is checked against a PERSISTENT
watchlist stored in the database (database.match_or_add_watchlist) — this
survives across separate program runs/days, so a stranger who keeps coming
back gets escalated to "repeat_offender" after enough sightings, even
though their in-memory temp ID resets every session.

Liveness (blink) checking runs alongside identity tracking — a face that
matches a registered person but never blinks gets flagged as spoof-suspected,
which overrides the normal "authorized" outcome.

Usage:
    from tracker import EntryExitTracker

    tracker = EntryExitTracker()
    tracker.update(results, frame)   # call once per processed frame
"""

import time
import os
import cv2
import numpy as np

from config import (
    EXIT_TIMEOUT_SECONDS, LOG_COOLDOWN_SECONDS, SNAPSHOTS_DIR,
    UNKNOWN_FACE_MATCH_TOLERANCE, UNKNOWN_ID_EXPIRY_SECONDS,
    ENABLE_LIVENESS_CHECK, REPEAT_OFFENDER_MATCH_TOLERANCE, REPEAT_OFFENDER_THRESHOLD,
    CONFIDENCE_MIN_FRAMES, ENABLE_TEXTURE_ANTISPOOF
)
from error_handler import logger, error_context
from database import log_event, match_or_add_watchlist
from liveness import LivenessChecker, TextureAntiSpoofChecker
from alerts import send_alert_email_async


class UnknownFaceRegistry:
    """
    Assigns and remembers temporary IDs for unrecognized faces, purely
    in-memory, so multiple simultaneous strangers can be tracked as
    distinct people during a session.
    """
    def __init__(self):
        self.clusters = {}  # temp_id -> {"embedding": np.array, "last_seen": ts}
        self._next_id = 1

    def get_temp_id(self, embedding, now):
        best_id, best_dist = None, None
        for temp_id, data in self.clusters.items():
            dist = np.linalg.norm(data["embedding"] - embedding)
            if best_dist is None or dist < best_dist:
                best_dist = dist
                best_id = temp_id

        if best_id is not None and best_dist <= UNKNOWN_FACE_MATCH_TOLERANCE:
            self.clusters[best_id]["embedding"] = embedding
            self.clusters[best_id]["last_seen"] = now
            return best_id

        new_id = f"unknown_{self._next_id}"
        self._next_id += 1
        self.clusters[new_id] = {"embedding": embedding, "last_seen": now}
        return new_id

    def cleanup(self, now):
        expired = [tid for tid, d in self.clusters.items()
                   if now - d["last_seen"] > UNKNOWN_ID_EXPIRY_SECONDS]
        for tid in expired:
            del self.clusters[tid]


class EntryExitTracker:
    def __init__(self, camera_location="Main Entrance"):
        # key -> {"present": bool, "last_seen": ts, "last_log_time": ts,
        #         "person": dict or None, "repeat_offender": bool, "sighting_count": int}
        self.state = {}
        self.unknown_registry = UnknownFaceRegistry()
        self.liveness = LivenessChecker()
        self.texture_checker = TextureAntiSpoofChecker()
        self.camera_location = camera_location

    def _key_for(self, result, now):
        person = result["person"]
        if person:
            return person["person_id"]
        return self.unknown_registry.get_temp_id(result["encoding"], now)

    def _save_snapshot(self, frame, key):
        try:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            safe_location = self.camera_location.replace(" ", "_").lower()
            filename = f"{safe_location}_{key}_{timestamp}.jpg"
            path = os.path.join(SNAPSHOTS_DIR, filename)
            cv2.imwrite(path, frame)
            return path
        except Exception as e:
            logger.warning(f"Could not save snapshot: {e}")
            return None

    def _check_watchlist(self, encoding, snapshot_path):
        """
        Checks a newly-appeared unknown face against the persistent
        cross-session watchlist. Returns (reason, sighting_count).
        """
        try:
            watch_id, count, is_new = match_or_add_watchlist(
                encoding, snapshot_path, REPEAT_OFFENDER_MATCH_TOLERANCE
            )
            if count >= REPEAT_OFFENDER_THRESHOLD:
                logger.warning(
                    f"REPEAT OFFENDER: unregistered visitor seen {count} times "
                    f"(watch_id={watch_id})"
                )
                return "repeat_offender", count
            return "unknown_face", count
        except Exception as e:
            logger.warning(f"Watchlist check failed: {e}")
            return "unknown_face", 1

    def _log(self, key, person, event_type, frame, spoof_suspected=False, encoding=None):
        with error_context(f"Logging {event_type} for key={key}"):
            snapshot_path = self._save_snapshot(frame, key) if frame is not None else None
            person_id = person["person_id"] if person else None

            sighting_count = None
            if spoof_suspected:
                reason = "spoof_suspected"
                is_suspicious = True
            elif person is None:
                is_suspicious = True
                if event_type == "ENTRY" and encoding is not None:
                    reason, sighting_count = self._check_watchlist(encoding, snapshot_path)
                    st = self.state.get(key)
                    if st is not None:
                        st["repeat_offender"] = (reason == "repeat_offender")
                        st["sighting_count"] = sighting_count
                else:
                    reason = "unknown_face"
            else:
                reason = None
                is_suspicious = False

            log_event(
                person_id=person_id,
                event_type=event_type,
                camera_location=self.camera_location,
                snapshot_path=snapshot_path,
                is_suspicious=is_suspicious,
                reason=reason
            )

            if event_type == "ENTRY" and is_suspicious:
                self._send_alert(reason, person, key, sighting_count, snapshot_path)

            if spoof_suspected and person is not None:
                who = f"{person['name']} — SPOOF SUSPECTED (no blink detected)"
            elif reason == "repeat_offender":
                who = f"unknown ({key}) — REPEAT OFFENDER, seen {sighting_count}x"
            else:
                who = person["name"] if person else f"unknown ({key})"
            logger.info(f"{event_type}: {who}")

    def _send_alert(self, reason, person, key, sighting_count, snapshot_path):
        if reason == "spoof_suspected":
            name = person["name"] if person else "an unregistered face"
            subject = "Spoof Attempt Detected"
            body = (f"A face matching '{name}' was detected but did not blink within the "
                    f"liveness timeout — likely a photo/video held up to the camera.\n\n"
                    f"Tracking key: {key}")
        elif reason == "repeat_offender":
            subject = "Repeat Unregistered Visitor"
            body = (f"An unregistered person has now been sighted {sighting_count} separate "
                    f"time(s) — escalated to repeat offender.\n\nTracking key: {key}")
        else:
            subject = "Unknown Person Detected"
            body = f"An unrecognized person was detected.\n\nTracking key: {key}"

        send_alert_email_async(subject, body, snapshot_path)

    def update(self, results, frame=None):
        """
        Call once per processed frame.
        `results` is the list returned by FaceEncoder.recognize().
        Mutates each result dict in place, adding: "is_live",
        "spoof_suspected", "repeat_offender".
        """
        now = time.time()
        seen_keys = set()

        for r in results:
            person = r["person"]
            key = self._key_for(r, now)
            seen_keys.add(key)

            if ENABLE_LIVENESS_CHECK:
                self.liveness.update(key, r.get("landmarks"), now)
                r["is_live"] = self.liveness.has_blinked(key)
                blink_spoof = self.liveness.is_spoof_suspected(key, now)
            else:
                r["is_live"] = True
                blink_spoof = False

            texture_spoof = False
            if ENABLE_TEXTURE_ANTISPOOF and frame is not None:
                top, right, bottom, left = r["box"]
                if bottom > top and right > left:
                    face_crop = frame[top:bottom, left:right]
                    texture_spoof = self.texture_checker.update(key, face_crop, now)

            # Combined signal: either a sustained lack of blinking OR
            # suspiciously flat image texture is enough to flag spoof —
            # texture can trigger faster (no need to wait for the blink
            # timeout), blink catches cases texture analysis might miss.
            r["spoof_suspected"] = blink_spoof or texture_spoof

            st = self.state.setdefault(key, {
                "present": False,
                "last_seen": now,
                "last_log_time": 0,
                "person": person,
                "repeat_offender": False,
                "sighting_count": None,
                "pending_frames": 0,
            })
            st["last_seen"] = now
            st["person"] = person

            if not st["present"]:
                # Require CONFIDENCE_MIN_FRAMES consecutive agreeing frames
                # before committing to ENTRY — filters out a single noisy
                # detection flipping the identity decision.
                st["pending_frames"] += 1
                if st["pending_frames"] >= CONFIDENCE_MIN_FRAMES:
                    if now - st["last_log_time"] >= LOG_COOLDOWN_SECONDS:
                        self._log(key, person, "ENTRY", frame,
                                  spoof_suspected=r["spoof_suspected"],
                                  encoding=r.get("encoding"))
                        st["last_log_time"] = now
                    st["present"] = True
                    st["pending_frames"] = 0

            r["confirmed"] = st["present"]

            # Reflect this key's watchlist status on the result every frame
            # (not just the ENTRY frame), so the live display stays consistent
            r["repeat_offender"] = st.get("repeat_offender", False)
            r["sighting_count"] = st.get("sighting_count")

        for key, st in self.state.items():
            if key in seen_keys:
                continue
            if not st["present"]:
                continue

            absent_for = now - st["last_seen"]
            if absent_for >= EXIT_TIMEOUT_SECONDS:
                if now - st["last_log_time"] >= LOG_COOLDOWN_SECONDS:
                    self._log(key, st["person"], "EXIT", frame)
                    st["last_log_time"] = now
                st["present"] = False
                self.liveness.forget(key)
                self.texture_checker.forget(key)

        self.unknown_registry.cleanup(now)