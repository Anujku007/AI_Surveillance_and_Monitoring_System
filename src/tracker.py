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
"unknown" bucket. These temp IDs are NOT saved to the database (the DB
still just marks such logs as is_suspicious=1 with person_id=NULL) — they
only exist in memory to keep ENTRY/EXIT logic correct while people are
on camera. If a stranger leaves and comes back after UNKNOWN_ID_EXPIRY_SECONDS,
they'll be treated as a "new" unknown person — a documented limitation.

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
    UNKNOWN_FACE_MATCH_TOLERANCE, UNKNOWN_ID_EXPIRY_SECONDS
)
from error_handler import logger, error_context
from database import log_event


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
            # Same stranger as a recent frame — refresh their record
            self.clusters[best_id]["embedding"] = embedding
            self.clusters[best_id]["last_seen"] = now
            return best_id

        # New stranger — assign a fresh temporary ID
        new_id = f"unknown_{self._next_id}"
        self._next_id += 1
        self.clusters[new_id] = {"embedding": embedding, "last_seen": now}
        return new_id

    def cleanup(self, now):
        """Drop temp IDs for strangers who've been gone a while, so the
        registry doesn't grow forever over a long-running session."""
        expired = [tid for tid, d in self.clusters.items()
                   if now - d["last_seen"] > UNKNOWN_ID_EXPIRY_SECONDS]
        for tid in expired:
            del self.clusters[tid]


class EntryExitTracker:
    def __init__(self):
        # key -> {"present": bool, "last_seen": ts, "last_log_time": ts, "person": dict or None}
        self.state = {}
        self.unknown_registry = UnknownFaceRegistry()

    def _key_for(self, result, now):
        """Registered persons are tracked individually by person_id.
        Unknown faces get a temporary ID from UnknownFaceRegistry, so
        different strangers don't collide into one shared bucket."""
        person = result["person"]
        if person:
            return person["person_id"]
        return self.unknown_registry.get_temp_id(result["encoding"], now)

    def _save_snapshot(self, frame, key):
        try:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filename = f"{key}_{timestamp}.jpg"
            path = os.path.join(SNAPSHOTS_DIR, filename)
            cv2.imwrite(path, frame)
            return path
        except Exception as e:
            logger.warning(f"Could not save snapshot: {e}")
            return None

    def _log(self, key, person, event_type, frame):
        with error_context(f"Logging {event_type} for key={key}"):
            snapshot_path = self._save_snapshot(frame, key) if frame is not None else None
            person_id = person["person_id"] if person else None
            log_event(
                person_id=person_id,
                event_type=event_type,
                snapshot_path=snapshot_path,
                is_suspicious=(person is None)
            )
            who = person["name"] if person else f"unknown ({key})"
            logger.info(f"{event_type}: {who}")

    def update(self, results, frame=None):
        """
        Call once per processed frame.
        `results` is the list returned by FaceEncoder.recognize():
            [{"box":..., "person": dict or None, "distance":..., "is_match": bool, "encoding":...}, ...]
        `frame` (optional) is used to save a snapshot when an event is logged.
        """
        now = time.time()
        seen_keys = set()

        # --- Handle everyone currently visible in this frame ---
        for r in results:
            person = r["person"]
            key = self._key_for(r, now)
            seen_keys.add(key)

            st = self.state.setdefault(key, {
                "present": False,
                "last_seen": now,
                "last_log_time": 0,
                "person": person
            })
            st["last_seen"] = now
            st["person"] = person

            if not st["present"]:
                if now - st["last_log_time"] >= LOG_COOLDOWN_SECONDS:
                    self._log(key, person, "ENTRY", frame)
                    st["last_log_time"] = now
                st["present"] = True

        # --- Handle people who were present but are no longer visible ---
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

        # Periodically clean up stale temporary unknown-face IDs
        self.unknown_registry.cleanup(now)