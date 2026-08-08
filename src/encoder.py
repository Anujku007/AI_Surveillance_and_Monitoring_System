"""
encoder.py
Face embedding (encoding) and comparison using the face_recognition library.

This module does NOT detect faces itself — it takes bounding boxes produced
by detector.py (OpenCV DNN) and turns each one into a 128-d embedding vector,
then compares those embeddings against the registered persons in the database.

Usage:
    from encoder import FaceEncoder

    encoder = FaceEncoder(known_persons)   # known_persons from database.get_all_persons()
    results = encoder.recognize(frame, boxes)
    # results -> list of dicts: {box, person_id, name, distance, is_match}
"""

import face_recognition
import numpy as np
import cv2

from config import FACE_MATCH_TOLERANCE
from error_handler import logger, error_context


class FaceEncoder:
    def __init__(self, known_persons=None):
        """
        known_persons: list of dicts from database.get_all_persons(),
        each containing 'person_id', 'name', 'embedding' (np.array).
        """
        self.known_persons = known_persons or []
        logger.info(f"FaceEncoder initialized with {len(self.known_persons)} known person(s)")

    def refresh_known_persons(self, known_persons):
        """Call this after registering a new person, so the in-memory list stays current."""
        self.known_persons = known_persons
        logger.info(f"Known persons refreshed: {len(self.known_persons)} total")

    def encode_faces(self, frame, boxes):
        """
        Converts each face bounding box into a 128-d embedding.
        `boxes` must be in (top, right, bottom, left) format — same as detector.py output.
        Returns a list of embeddings, same order as boxes.
        """
        with error_context("Encoding detected faces"):
            # face_recognition expects RGB, OpenCV gives BGR.
            # NOTE: use cv2.cvtColor (not frame[:, :, ::-1]) — the slice
            # trick creates a non-contiguous array that dlib's pybind11
            # bindings reject with a confusing "no overload matches" error.
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            encodings = face_recognition.face_encodings(rgb_frame, boxes)
            return encodings

    def match_encoding(self, encoding):
        """
        Compares one face embedding against all known persons.
        Returns (person_dict or None, distance) for the closest match
        within tolerance, or (None, None) if no known faces exist yet.
        """
        if not self.known_persons:
            return None, None

        known_embeddings = [p["embedding"] for p in self.known_persons]
        distances = face_recognition.face_distance(known_embeddings, encoding)

        best_index = np.argmin(distances)
        best_distance = distances[best_index]

        if best_distance <= FACE_MATCH_TOLERANCE:
            return self.known_persons[best_index], float(best_distance)

        return None, float(best_distance)

    def get_landmarks(self, frame, boxes):
        """
        Extracts facial landmarks (eyes, nose, mouth, etc.) for each detected
        face — used for liveness/blink detection, not for identity matching.
        Returns a list of landmark dicts, same order as boxes. Each dict has
        keys like 'left_eye' and 'right_eye', each a list of 6 (x, y) points.
        """
        with error_context("Extracting facial landmarks"):
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            return face_recognition.face_landmarks(rgb_frame, boxes)

    def recognize(self, frame, boxes):
        """
        Full pipeline: encode each detected face, match it against known
        persons, and extract landmarks for liveness checking.

        Returns a list of dicts, one per face:
            {
                "box": (top, right, bottom, left),
                "person": person_dict or None,   # None = unknown/unregistered
                "distance": float or None,
                "is_match": bool,
                "encoding": np.array,             # raw 128-d embedding
                "landmarks": dict or None         # eye points for liveness check
            }
        """
        results = []
        encodings = self.encode_faces(frame, boxes)
        landmarks_list = self.get_landmarks(frame, boxes)

        for box, encoding, landmarks in zip(boxes, encodings, landmarks_list):
            person, distance = self.match_encoding(encoding)
            results.append({
                "box": box,
                "person": person,
                "distance": distance,
                "is_match": person is not None,
                "encoding": encoding,
                "landmarks": landmarks
            })

        return results


# ---------------------------------------------------------
# Quick manual test — live webcam recognition against the database
# ---------------------------------------------------------
if __name__ == "__main__":
    import cv2
    from config import CAMERA_INDEX, COLOR_KNOWN, COLOR_UNKNOWN
    from detector import FaceDetector
    from database import init_db, get_all_persons

    init_db()
    detector = FaceDetector()
    encoder = FaceEncoder(get_all_persons())

    cap = cv2.VideoCapture(CAMERA_INDEX)
    if not cap.isOpened():
        logger.error("Could not open webcam")
    else:
        logger.info("Press 'q' to quit the encoder test")
        while True:
            ret, frame = cap.read()
            if not ret:
                logger.warning("Failed to read frame from camera")
                break

            boxes = detector.detect(frame)
            results = encoder.recognize(frame, boxes)

            for r in results:
                top, right, bottom, left = r["box"]
                if r["is_match"]:
                    color = COLOR_KNOWN
                    label = f"{r['person']['name']} ({r['distance']:.2f})"
                else:
                    color = COLOR_UNKNOWN
                    label = "Unknown"

                cv2.rectangle(frame, (left, top), (right, bottom), color, 2)
                cv2.putText(frame, label, (left, top - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

            cv2.imshow("Encoder Test", frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

        cap.release()
        cv2.destroyAllWindows()