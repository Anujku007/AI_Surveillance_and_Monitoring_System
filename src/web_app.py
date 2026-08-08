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

from config import KNOWN_FACES_DIR, SNAPSHOTS_DIR
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

live_controller = LiveFeedController()
reg_camera = RegistrationCamera()
reg_encoder = FaceEncoder()


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
# Live monitoring
# ---------------------------------------------------------
@app.route("/api/live/start", methods=["POST"])
@login_required
def live_start():
    if reg_camera.running:
        return jsonify(success=False, message="Registration camera is active. Stop it first."), 400
    ok = live_controller.start()
    return jsonify(success=ok)


@app.route("/api/live/stop", methods=["POST"])
@login_required
def live_stop():
    live_controller.stop()
    return jsonify(success=True)


@app.route("/api/live/stats")
@login_required
def live_stats():
    return jsonify(running=live_controller.running, **live_controller.get_stats())


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


@app.route("/video_feed")
@login_required
def video_feed():
    return Response(_mjpeg_generator(live_controller.get_latest_frame),
                     mimetype="multipart/x-mixed-replace; boundary=frame")


# ---------------------------------------------------------
# Registration
# ---------------------------------------------------------
@app.route("/api/register/start", methods=["POST"])
@login_required
def register_start():
    if live_controller.running:
        return jsonify(success=False, message="Live monitoring is active. Stop it first."), 400
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
        live_controller.refresh_known_persons()
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


if __name__ == "__main__":
    logger.info("Starting web app at http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)