"""
main.py
Main entry point for the AI-Based Intelligent Surveillance System.

Runs the live camera loop:
    capture -> detect -> recognize -> track entry/exit -> display -> log

Usage:
    python main.py
"""

import cv2
import time
import platform

from config import (
    CAMERA_INDEX, PROCESS_EVERY_N_FRAMES,
    COLOR_KNOWN, COLOR_UNKNOWN, COLOR_SPOOF, COLOR_REPEAT, COLOR_VERIFYING,
    ENABLE_ALERT_SOUND, ALERT_COOLDOWN_SECONDS
)
from error_handler import logger, safe_run
from database import init_db, get_all_persons
from detector import FaceDetector
from encoder import FaceEncoder
from tracker import EntryExitTracker

# winsound is Windows-only and built into the standard library — no install needed.
# On other platforms, alerts are silently disabled rather than crashing.
if platform.system() == "Windows":
    import winsound
    SOUND_AVAILABLE = True
else:
    SOUND_AVAILABLE = False

UI_BG = (30, 30, 30)          # dark overlay bar background
UI_TEXT = (255, 255, 255)     # white text
UI_ACCENT = (0, 210, 255)     # amber/cyan accent for headings


def play_alert():
    """Plays a short, non-blocking alert sound when a suspicious/unknown
    person is detected. Silently does nothing on unsupported platforms."""
    if not (ENABLE_ALERT_SOUND and SOUND_AVAILABLE):
        return
    try:
        winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
    except Exception as e:
        logger.warning(f"Could not play alert sound: {e}")


def draw_overlay_bar(frame, fps, face_count, known_count, unknown_count):
    """Draws a semi-transparent status bar across the top of the frame."""
    h, w = frame.shape[:2]
    bar_height = 40

    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (w, bar_height), UI_BG, cv2.FILLED)
    cv2.addWeighted(overlay, 0.65, frame, 0.35, 0, frame)

    cv2.putText(frame, "AI SURVEILLANCE SYSTEM", (10, 26),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, UI_ACCENT, 2)

    stats_text = f"FPS: {fps:4.1f}  |  Faces: {face_count}  (OK: {known_count}  ALERT: {unknown_count})"
    text_size = cv2.getTextSize(stats_text, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)[0]
    cv2.putText(frame, stats_text, (w - text_size[0] - 15, 26),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, UI_TEXT, 1)

    return frame


def draw_results(frame, results):
    """Draws bounding boxes + labels for each detected face on the frame."""
    known_count = 0
    unknown_count = 0
    spoof_count = 0
    repeat_count = 0

    for r in results:
        top, right, bottom, left = r["box"]

        if r.get("spoof_suspected"):
            color = COLOR_SPOOF
            name = r["person"]["name"] if r["is_match"] else "Unknown"
            label = f"SPOOF SUSPECTED ({name})"
            spoof_count += 1
        elif not r.get("confirmed", True):
            color = COLOR_VERIFYING
            label = "Verifying..."
        elif r.get("repeat_offender"):
            color = COLOR_REPEAT
            count = r.get("sighting_count") or "?"
            label = f"REPEAT VISITOR ({count}x seen)"
            repeat_count += 1
        elif r["is_match"]:
            color = COLOR_KNOWN
            label = f"{r['person']['name']} ({r['distance']:.2f})"
            known_count += 1
        else:
            color = COLOR_UNKNOWN
            label = "UNKNOWN - ALERT"
            unknown_count += 1

        cv2.rectangle(frame, (left, top), (right, bottom), color, 2)
        # Filled label background for readability
        label_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)[0]
        cv2.rectangle(frame, (left, bottom), (left + label_size[0] + 10, bottom + 24), color, cv2.FILLED)
        cv2.putText(frame, label, (left + 5, bottom + 17),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

    return frame, known_count, unknown_count, spoof_count, repeat_count


@safe_run
def process_frame(frame, detector, encoder):
    """Runs detection + recognition on a single frame. Wrapped in safe_run
    so one bad frame (e.g. a decode glitch) can't crash the whole loop."""
    boxes = detector.detect(frame)
    results = encoder.recognize(frame, boxes)
    return results


def main():
    logger.info("Starting AI Surveillance System...")

    # --- Critical startup steps: allowed to crash loudly if they fail ---
    init_db()
    detector = FaceDetector()
    encoder = FaceEncoder(get_all_persons())
    tracker = EntryExitTracker()

    cap = cv2.VideoCapture(CAMERA_INDEX)
    if not cap.isOpened():
        logger.error("FATAL: Could not open webcam. Check CAMERA_INDEX in config.py.")
        return

    logger.info("Camera opened. Press 'q' to quit, 'r' to reload known faces from database.")
    if ENABLE_ALERT_SOUND and not SOUND_AVAILABLE:
        logger.warning("Alert sound is enabled in config but not supported on this OS.")

    frame_count = 0
    last_results = []
    last_alert_time = 0

    # FPS tracking (smoothed over recent frames, not just instant delta)
    fps = 0.0
    fps_last_time = time.time()
    fps_frame_counter = 0

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                logger.warning("Failed to read frame from camera. Retrying...")
                time.sleep(0.1)
                continue

            frame_count += 1
            fps_frame_counter += 1

            # Update FPS roughly once per second, not every frame (less jittery display)
            now = time.time()
            if now - fps_last_time >= 1.0:
                fps = fps_frame_counter / (now - fps_last_time)
                fps_frame_counter = 0
                fps_last_time = now

            # Only run the expensive detect+encode pipeline every N frames
            if frame_count % PROCESS_EVERY_N_FRAMES == 0:
                results = process_frame(frame, detector, encoder)
                if results is not None:
                    last_results = results
                    tracker.update(results, frame)

            display_frame, known_count, unknown_count, spoof_count, repeat_count = draw_results(frame.copy(), last_results)
            display_frame = draw_overlay_bar(display_frame, fps, len(last_results), known_count, unknown_count)

            # Alert sound — for unrecognized, spoof-suspected, or repeat-offender
            # faces, respecting a cooldown so it doesn't beep every single frame
            if (unknown_count > 0 or spoof_count > 0 or repeat_count > 0) and \
                    (now - last_alert_time) >= ALERT_COOLDOWN_SECONDS:
                play_alert()
                last_alert_time = now

            cv2.imshow("AI Surveillance System", display_frame)

            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                logger.info("Quit key pressed. Shutting down...")
                break
            elif key == ord('r'):
                encoder.refresh_known_persons(get_all_persons())
                logger.info("Known faces reloaded from database.")

    except KeyboardInterrupt:
        logger.info("Interrupted by user (Ctrl+C). Shutting down...")

    finally:
        cap.release()
        cv2.destroyAllWindows()
        logger.info("Camera released. System stopped.")


if __name__ == "__main__":
    main()