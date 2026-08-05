"""
register_faces.py
Interactive script to register a new person into the surveillance database.

Captures a photo from the webcam, detects the face, generates its embedding,
and saves the person's details + embedding into the database.

Usage:
    python register_faces.py
"""

import cv2
import os
from datetime import datetime

from config import CAMERA_INDEX, KNOWN_FACES_DIR, COLOR_KNOWN, COLOR_UNKNOWN
from error_handler import logger
from detector import FaceDetector
from encoder import FaceEncoder
from database import init_db, add_person, get_all_persons


def capture_face_photo():
    """
    Opens the webcam and lets the user position their face, then capture
    a photo by pressing SPACE. Returns the captured frame, or None if cancelled.
    Shows a live box (green if exactly one face, red otherwise) as guidance.
    """
    detector = FaceDetector()
    cap = cv2.VideoCapture(CAMERA_INDEX)

    if not cap.isOpened():
        logger.error("Could not open webcam")
        return None

    print("\nPosition your face in the frame.")
    print("Press SPACE to capture, or 'q' to cancel.\n")

    captured_frame = None

    while True:
        ret, frame = cap.read()
        if not ret:
            logger.warning("Failed to read frame from camera")
            break

        boxes = detector.detect(frame)
        display = frame.copy()

        # Guide the user: green box = exactly one face detected (ready to capture)
        color = COLOR_KNOWN if len(boxes) == 1 else COLOR_UNKNOWN
        for (top, right, bottom, left) in boxes:
            cv2.rectangle(display, (left, top), (right, bottom), color, 2)

        status = f"Faces detected: {len(boxes)}"
        if len(boxes) == 1:
            status += "  -  Press SPACE to capture"
        elif len(boxes) == 0:
            status += "  -  No face found"
        else:
            status += "  -  Only one person should be in frame"

        cv2.putText(display, status, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
        cv2.imshow("Register Face", display)

        key = cv2.waitKey(1) & 0xFF
        if key == ord(' ') and len(boxes) == 1:
            captured_frame = frame.copy()
            break
        elif key == ord('q'):
            print("Registration cancelled.")
            break

    cap.release()
    cv2.destroyAllWindows()
    return captured_frame


def register_new_person():
    """Runs the full interactive registration flow."""
    init_db()

    name = input("Enter full name: ").strip()
    identifier = input("Enter ID/Roll number: ").strip()
    organization = input("Enter organization/department: ").strip()

    if not name or not identifier:
        logger.error("Name and ID are required. Registration aborted.")
        return

    frame = capture_face_photo()
    if frame is None:
        logger.warning("No photo captured. Registration aborted.")
        return

    # Detect + encode the captured photo
    detector = FaceDetector()
    encoder = FaceEncoder()

    boxes = detector.detect(frame)
    if len(boxes) != 1:
        logger.error(f"Expected exactly 1 face in captured photo, found {len(boxes)}. Try again.")
        return

    encodings = encoder.encode_faces(frame, boxes)
    if not encodings:
        logger.error("Could not generate a face embedding from the captured photo.")
        return

    embedding = encodings[0]

    # Save the photo for reference (not strictly needed for recognition,
    # but useful for your report/demo and for manually verifying registrations)
    os.makedirs(KNOWN_FACES_DIR, exist_ok=True)
    safe_name = name.replace(" ", "_").lower()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    photo_filename = f"{safe_name}_{timestamp}.jpg"
    photo_path = os.path.join(KNOWN_FACES_DIR, photo_filename)
    cv2.imwrite(photo_path, frame)

    # Save to database
    person_id = add_person(
        name=name,
        identifier=identifier,
        organization=organization,
        embedding=embedding,
        photo_path=photo_path
    )

    if person_id:
        print(f"\n✅ Successfully registered '{name}' (person_id={person_id})")
        print(f"   Photo saved at: {photo_path}\n")
    else:
        logger.error("Registration failed — could not save to database.")


def list_registered_persons():
    """Prints all currently registered persons — useful to verify the database."""
    init_db()
    persons = get_all_persons()

    if not persons:
        print("\nNo persons registered yet.\n")
        return

    print(f"\n--- Registered Persons ({len(persons)}) ---")
    for p in persons:
        print(f"  ID: {p['person_id']:<4} | Name: {p['name']:<20} | "
              f"Identifier: {p['identifier']:<12} | Org: {p['organization']}")
    print()


if __name__ == "__main__":
    print("=== AI Surveillance System — Face Registration ===\n")
    print("1. Register a new person")
    print("2. List registered persons")
    choice = input("\nChoose an option (1/2): ").strip()

    if choice == "1":
        register_new_person()
    elif choice == "2":
        list_registered_persons()
    else:
        print("Invalid choice.")