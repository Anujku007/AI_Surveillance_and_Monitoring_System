"""
detector.py
Face detection using OpenCV's DNN module (ResNet-SSD, Caffe model).

Usage:
    from detector import FaceDetector

    detector = FaceDetector()
    boxes = detector.detect(frame)   # list of (top, right, bottom, left)
"""

import cv2
import numpy as np

from config import PROTOTXT_PATH, CAFFEMODEL_PATH, DETECTION_CONFIDENCE_THRESHOLD
from error_handler import logger, error_context


class FaceDetector:
    def __init__(self):
        with error_context("Loading OpenCV DNN face detector"):
            self.net = cv2.dnn.readNetFromCaffe(PROTOTXT_PATH, CAFFEMODEL_PATH)
            logger.info("Face detector model loaded successfully")

    def detect(self, frame):
        """
        Detects faces in a BGR frame (as read by cv2.VideoCapture).

        Returns a list of bounding boxes in (top, right, bottom, left) format —
        this matches the format face_recognition.face_encodings() expects,
        so the output plugs directly into encoder.py without conversion.
        """
        if self.net is None:
            logger.error("Detector called but model was not loaded")
            return []

        (h, w) = frame.shape[:2]

        blob = cv2.dnn.blobFromImage(
            cv2.resize(frame, (300, 300)),
            1.0,
            (300, 300),
            (104.0, 177.0, 123.0)
        )

        self.net.setInput(blob)
        detections = self.net.forward()

        boxes = []
        for i in range(detections.shape[2]):
            confidence = detections[0, 0, i, 2]

            if confidence < DETECTION_CONFIDENCE_THRESHOLD:
                continue

            box = detections[0, 0, i, 3:7] * np.array([w, h, w, h])
            (start_x, start_y, end_x, end_y) = box.astype("int")

            # Clip to frame boundaries (DNN can occasionally return slightly
            # out-of-bounds coordinates near frame edges)
            start_x, start_y = max(0, start_x), max(0, start_y)
            end_x, end_y = min(w - 1, end_x), min(h - 1, end_y)

            # Convert (start_x, start_y, end_x, end_y) -> (top, right, bottom, left)
            # to match face_recognition's expected box format
            top, right, bottom, left = start_y, end_x, end_y, start_x
            boxes.append((top, right, bottom, left))

        return boxes


# ---------------------------------------------------------
# Quick manual test — draws boxes on a live webcam feed
# ---------------------------------------------------------
if __name__ == "__main__":
    from config import CAMERA_INDEX

    detector = FaceDetector()
    cap = cv2.VideoCapture(CAMERA_INDEX)

    if not cap.isOpened():
        logger.error("Could not open webcam")
    else:
        logger.info("Press 'q' to quit the detector test")
        while True:
            ret, frame = cap.read()
            if not ret:
                logger.warning("Failed to read frame from camera")
                break

            boxes = detector.detect(frame)
            for (top, right, bottom, left) in boxes:
                cv2.rectangle(frame, (left, top), (right, bottom), (0, 255, 0), 2)

            cv2.putText(frame, f"Faces: {len(boxes)}", (10, 25),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

            cv2.imshow("Detector Test", frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

        cap.release()
        cv2.destroyAllWindows()