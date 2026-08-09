"""
web_app.py
Flask web front end for the AI Surveillance System.

Replaces the Tkinter app.py — same underlying logic (LiveFeedController,
RegistrationCamera, database, report_generator), served as a local web app.

Usage:
    python web_app.py
    then open http://127.0.0.1:5000 in a browser
"""

import os
import time
import cv2
from functools import wraps
from datetime import datetime

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, jsonify, send_file, Response
)
from werkzeug.utils import secure_filename

from config import KNOWN_FACES_DIR, SNAPSHOTS_DIR, CAMERAS, get_current_settings, save_settings
from database import init_db, get_all_logs, add_person
from error_handler import logger
from report_generator import generate_pdf_report
from live_feed import LiveFeedController
from registration_panel import RegistrationCamera
from encoder import FaceEncoder
from auth import is_password_set, set_password, verify_password
from dashboard import build_sessions

app = Flask(__name__)
app.secret_key = os.urandom(24)  # session resets each restart — fine for local single-user use

init_db()

# One LiveFeedController per configured camera, keyed by camera id
live_controllers = {
    cam["id"]: LiveFeedController(camera_source=cam["source"], camera_name=cam["name"])
    for cam in CAMERAS
}
reg_camera = RegistrationCamera()
reg_encoder = FaceEncoder()


def any_live_camera_running():
    return any(c.running for c in live_controllers.values())


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------
# Auth
# ---------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    first_time = not is_password_set()
    error = None

    if request.method == "POST":
        password = request.form.get("password", "")

        if first_time:
            confirm = request.form.get("confirm", "")
            if len(password) < 4:
                error = "Password must be at least 4 characters."
            elif password != confirm:
                error = "Passwords do not match."
            else:
                set_password(password)
                logger.info("Admin password created.")
                session["logged_in"] = True
                return redirect(url_for("index"))
        else:
            attempts = session.get("attempts", 0)
            if verify_password(password):
                session["logged_in"] = True
                session["attempts"] = 0
                return redirect(url_for("index"))
            attempts += 1
            session["attempts"] = attempts
            if attempts >= 5:
                error = "Too many failed attempts. Restart the app to try again."
                logger.warning("Too many failed web login attempts.")
            else:
                error = f"Incorrect password. {5 - attempts} attempt(s) left."

    return render_template("login.html", first_time=first_time, error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    return render_template("dashboard.html")


# ---------------------------------------------------------
# Live monitoring (multi-camera)
# ---------------------------------------------------------
@app.route("/api/cameras")
@login_required
def api_cameras():
    return jsonify([{"id": cam["id"], "name": cam["name"]} for cam in CAMERAS])


@app.route("/api/live/start/<camera_id>", methods=["POST"])
@login_required
def live_start(camera_id):
    controller = live_controllers.get(camera_id)
    if controller is None:
        return jsonify(success=False, message="Unknown camera."), 404
    if reg_camera.running:
        return jsonify(success=False, message="Registration camera is active. Stop it first."), 400
    ok = controller.start()
    return jsonify(success=ok)


@app.route("/api/live/stop/<camera_id>", methods=["POST"])
@login_required
def live_stop(camera_id):
    controller = live_controllers.get(camera_id)
    if controller is None:
        return jsonify(success=False, message="Unknown camera."), 404
    controller.stop()
    return jsonify(success=True)


@app.route("/api/live/stats/<camera_id>")
@login_required
def live_stats(camera_id):
    controller = live_controllers.get(camera_id)
    if controller is None:
        return jsonify(success=False, message="Unknown camera."), 404
    return jsonify(running=controller.running, **controller.get_stats())


def _mjpeg_generator(get_frame_func):
    while True:
        frame = get_frame_func()
        if frame is None:
            time.sleep(0.05)
            continue
        ok, buf = cv2.imencode(".jpg", frame)
        if not ok:
            continue
        yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n")
        time.sleep(0.03)


@app.route("/video_feed/<camera_id>")
@login_required
def video_feed(camera_id):
    controller = live_controllers.get(camera_id)
    if controller is None:
        return "", 404
    return Response(_mjpeg_generator(controller.get_latest_frame),
                     mimetype="multipart/x-mixed-replace; boundary=frame")


# ---------------------------------------------------------
# Registration
# ---------------------------------------------------------
@app.route("/api/register/start", methods=["POST"])
@login_required
def register_start():
    if any_live_camera_running():
        return jsonify(success=False, message="Live monitoring is active. Stop all cameras first."), 400
    ok = reg_camera.start()
    return jsonify(success=ok)


@app.route("/api/register/stop", methods=["POST"])
@login_required
def register_stop():
    reg_camera.stop()
    return jsonify(success=True)


@app.route("/api/register/status")
@login_required
def register_status():
    return jsonify(running=reg_camera.running, face_count=reg_camera.get_face_count())


@app.route("/video_feed_register")
@login_required
def video_feed_register():
    return Response(_mjpeg_generator(reg_camera.get_preview_frame),
                     mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/api/register/capture", methods=["POST"])
@login_required
def register_capture():
    name = request.form.get("name", "").strip()
    identifier = request.form.get("identifier", "").strip()
    organization = request.form.get("organization", "").strip()

    if not name or not identifier:
        return jsonify(success=False, message="Name and ID are required."), 400
    if reg_camera.get_face_count() != 1:
        return jsonify(success=False, message="Exactly one face must be visible."), 400

    raw_frame = reg_camera.capture_raw_frame()
    if raw_frame is None:
        return jsonify(success=False, message="No frame available."), 400

    boxes = reg_camera.detector.detect(raw_frame)
    if len(boxes) != 1:
        return jsonify(success=False, message="Face detection changed — try again."), 400

    encodings = reg_encoder.encode_faces(raw_frame, boxes)
    if not encodings:
        return jsonify(success=False, message="Could not generate face embedding."), 400

    os.makedirs(KNOWN_FACES_DIR, exist_ok=True)
    safe_name = name.replace(" ", "_").lower()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    photo_path = os.path.join(KNOWN_FACES_DIR, f"{safe_name}_{timestamp}.jpg")
    cv2.imwrite(photo_path, raw_frame)

    person_id = add_person(name=name, identifier=identifier, organization=organization,
                            embedding=encodings[0], photo_path=photo_path)
    if person_id:
        for controller in live_controllers.values():
            controller.refresh_known_persons()
        return jsonify(success=True, person_id=person_id)
    return jsonify(success=False, message="Database error — could not save."), 500


# ---------------------------------------------------------
# Logs
# ---------------------------------------------------------
def _basename_or_none(path):
    return os.path.basename(path) if path else None


@app.route("/api/logs/events")
@login_required
def api_events():
    logs = get_all_logs(limit=500)
    for log in logs:
        log["snapshot_file"] = _basename_or_none(log.get("snapshot_path"))
    return jsonify(logs)


@app.route("/api/logs/sessions")
@login_required
def api_sessions():
    logs = get_all_logs(limit=500)
    sessions = build_sessions(logs)
    for s in sessions:
        s["snapshot_file"] = _basename_or_none(s.get("entry_snapshot"))
    return jsonify(sessions)


@app.route("/api/snapshot/<filename>")
@login_required
def api_snapshot(filename):
    filename = secure_filename(filename)
    full_path = os.path.join(SNAPSHOTS_DIR, filename)
    if not os.path.exists(full_path):
        return "", 404
    return send_file(full_path, mimetype="image/jpeg")


@app.route("/api/report")
@login_required
def api_report():
    path = generate_pdf_report()
    return send_file(path, as_attachment=True)


# ---------------------------------------------------------
# Analytics
# ---------------------------------------------------------
# ---------------------------------------------------------
# Settings
# ---------------------------------------------------------
@app.route("/api/settings", methods=["GET"])
@login_required
def api_get_settings():
    return jsonify(get_current_settings())


@app.route("/api/settings", methods=["POST"])
@login_required
def api_save_settings():
    if any_live_camera_running() or reg_camera.running:
        return jsonify(success=False,
                        message="Stop all cameras before changing settings."), 400

    new_values = request.get_json(force=True, silent=True) or {}
    try:
        save_settings(new_values)
        logger.info(f"Settings updated: {list(new_values.keys())}")
        return jsonify(success=True, message="Saved. Restart the app for changes to take effect.")
    except Exception as e:
        logger.error(f"Could not save settings: {e}")
        return jsonify(success=False, message=str(e)), 500


@app.route("/api/analytics")
@login_required
def api_analytics():
    logs = get_all_logs(limit=2000)

    entries_per_day = {}
    peak_hours = {h: 0 for h in range(24)}
    top_visitors = {}
    authorized_count = 0
    suspicious_count = 0
    reason_counts = {"unknown_face": 0, "spoof_suspected": 0, "repeat_offender": 0}

    for log in logs:
        if log["event_type"] != "ENTRY":
            continue

        ts = log["timestamp"]
        day = ts[:10]
        hour = int(ts[11:13])

        entries_per_day[day] = entries_per_day.get(day, 0) + 1
        peak_hours[hour] += 1

        if log["is_suspicious"]:
            suspicious_count += 1
            reason = log.get("reason") or "unknown_face"
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
        else:
            authorized_count += 1
            name = log["name"] or "Unknown"
            top_visitors[name] = top_visitors.get(name, 0) + 1

    sorted_days = sorted(entries_per_day.keys())
    top_visitors_sorted = sorted(top_visitors.items(), key=lambda x: x[1], reverse=True)[:5]

    return jsonify({
        "entries_per_day": {"labels": sorted_days, "values": [entries_per_day[d] for d in sorted_days]},
        "peak_hours": {"labels": [f"{h:02d}:00" for h in range(24)], "values": [peak_hours[h] for h in range(24)]},
        "authorized_vs_suspicious": {"authorized": authorized_count, "suspicious": suspicious_count},
        "reason_breakdown": reason_counts,
        "top_visitors": {"labels": [v[0] for v in top_visitors_sorted], "values": [v[1] for v in top_visitors_sorted]},
    })


if __name__ == "__main__":
    logger.info("Starting web app at http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)