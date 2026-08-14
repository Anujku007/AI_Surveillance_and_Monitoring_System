"""
web_app.py
Flask web front end for the AI Surveillance System — hardened for closer-to-
production use:
    - Multi-user accounts with roles (admin / guard / viewer), replacing the
      old single-admin password file
    - CSRF protection on all browser-submitted forms
    - Secure session cookies (HttpOnly, SameSite, Secure when HTTPS is on)
    - Rate limiting on the login route (network-level brute-force defense,
      on top of the existing per-session attempt counter)
    - Persistent Flask secret key via .env (sessions survive restarts)
    - Optional self-signed HTTPS for local demo/testing

Usage:
    python web_app.py
    then open http://127.0.0.1:5000 (or https:// if ENABLE_HTTPS is on)
"""

import os
import time
import secrets
import cv2
from functools import wraps
from datetime import datetime

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, jsonify, send_file, Response
)
from werkzeug.utils import secure_filename
from flask_wtf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv

from config import KNOWN_FACES_DIR, SNAPSHOTS_DIR, CAMERAS, DATABASE_DIR, ENABLE_HTTPS, RETENTION_DAYS
import config as app_config
from database import (
    init_db, get_all_logs, add_person,
    any_users_exist, create_user, verify_login, get_all_users, delete_user,
    log_audit, get_audit_log, purge_old_data
)
from error_handler import logger
from report_generator import generate_pdf_report
from live_feed import LiveFeedController
from registration_panel import RegistrationCamera
from encoder import FaceEncoder
from dashboard import build_sessions

# ---------------------------------------------------------
# Persistent secret key (.env), so sessions survive restarts
# ---------------------------------------------------------
ENV_PATH = os.path.join(DATABASE_DIR, ".env")
if not os.path.exists(ENV_PATH):
    with open(ENV_PATH, "w") as f:
        f.write(f"FLASK_SECRET_KEY={secrets.token_hex(32)}\n")
load_dotenv(ENV_PATH)

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", secrets.token_hex(32))

# Secure cookie settings — Secure flag only makes sense when actually
# serving over HTTPS, otherwise browsers will just drop the cookie.
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=ENABLE_HTTPS,
)

csrf = CSRFProtect(app)
limiter = Limiter(app=app, key_func=get_remote_address, default_limits=[])

init_db()

if RETENTION_DAYS > 0:
    purge_old_data(RETENTION_DAYS)

live_controllers = {
    cam["id"]: LiveFeedController(camera_source=cam["source"], camera_name=cam["name"])
    for cam in CAMERAS
}
reg_camera = RegistrationCamera()
reg_encoder = FaceEncoder()


def any_live_camera_running():
    return any(c.running for c in live_controllers.values())


# ---------------------------------------------------------
# Auth decorators
# ---------------------------------------------------------
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


def role_required(*allowed_roles):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            user = session.get("user")
            if not user:
                return redirect(url_for("login"))
            if user["role"] not in allowed_roles:
                return jsonify(success=False, message="Insufficient permissions for this action."), 403
            return f(*args, **kwargs)
        return wrapper
    return decorator


# ---------------------------------------------------------
# Auth routes
# ---------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def login():
    first_time = not any_users_exist()
    error = None

    if request.method == "POST":
        if first_time:
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            confirm = request.form.get("confirm", "")
            if len(username) < 3:
                error = "Username must be at least 3 characters."
            elif len(password) < 4:
                error = "Password must be at least 4 characters."
            elif password != confirm:
                error = "Passwords do not match."
            else:
                create_user(username, password, role="admin")
                user = verify_login(username, password)
                session["user"] = user
                logger.info(f"First admin account created: {username}")
                log_audit(username, "ACCOUNT_CREATED", "First admin account (initial setup)")
                log_audit(username, "LOGIN", "First login after setup")
                return redirect(url_for("index"))
        else:
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            attempts = session.get("attempts", 0)

            user = verify_login(username, password)
            if user:
                session["user"] = user
                session["attempts"] = 0
                log_audit(username, "LOGIN", "")
                return redirect(url_for("index"))

            attempts += 1
            session["attempts"] = attempts
            if attempts >= 5:
                error = "Too many failed attempts. Please wait a minute and try again."
                logger.warning(f"Too many failed web login attempts for username '{username}'.")
                log_audit(username, "LOGIN_LOCKOUT", "5 failed attempts")
            else:
                error = f"Incorrect username or password. {5 - attempts} attempt(s) left."

    return render_template("login.html", first_time=first_time, error=error)


@app.route("/logout")
def logout():
    if session.get("user"):
        log_audit(session["user"]["username"], "LOGOUT", "")
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    return render_template("dashboard.html", role=session["user"]["role"])


# ---------------------------------------------------------
# User management (admin only)
# ---------------------------------------------------------
@app.route("/users", methods=["GET", "POST"])
@role_required("admin")
def users_page():
    error = None
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            role = request.form.get("role", "viewer")
            if role not in ("admin", "guard", "viewer"):
                error = "Invalid role."
            elif len(username) < 3 or len(password) < 4:
                error = "Username (3+ chars) and password (4+ chars) are required."
            else:
                try:
                    create_user(username, password, role)
                    log_audit(session["user"]["username"], "USER_CREATED", f"username={username}, role={role}")
                except Exception as e:
                    error = f"Could not create user (username may already exist): {e}"
        elif action == "delete":
            user_id = int(request.form.get("user_id"))
            if user_id == session["user"]["user_id"]:
                error = "You cannot delete your own account while logged in."
            else:
                delete_user(user_id)
                log_audit(session["user"]["username"], "USER_DELETED", f"user_id={user_id}")

    return render_template("users.html", users=get_all_users(), error=error)


# ---------------------------------------------------------
# Live monitoring (multi-camera) — admin + guard only
# ---------------------------------------------------------
@app.route("/api/cameras")
@login_required
def api_cameras():
    return jsonify([{"id": cam["id"], "name": cam["name"]} for cam in CAMERAS])


@app.route("/api/live/start/<camera_id>", methods=["POST"])
@role_required("admin", "guard")
@csrf.exempt
def live_start(camera_id):
    controller = live_controllers.get(camera_id)
    if controller is None:
        return jsonify(success=False, message="Unknown camera."), 404
    if reg_camera.running:
        return jsonify(success=False, message="Registration camera is active. Stop it first."), 400
    ok = controller.start()
    return jsonify(success=ok)


@app.route("/api/live/stop/<camera_id>", methods=["POST"])
@role_required("admin", "guard")
@csrf.exempt
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
# Registration — admin only
# ---------------------------------------------------------
@app.route("/api/register/start", methods=["POST"])
@role_required("admin")
@csrf.exempt
def register_start():
    if any_live_camera_running():
        return jsonify(success=False, message="Live monitoring is active. Stop all cameras first."), 400
    ok = reg_camera.start()
    return jsonify(success=ok)


@app.route("/api/register/stop", methods=["POST"])
@role_required("admin")
@csrf.exempt
def register_stop():
    reg_camera.stop()
    return jsonify(success=True)


@app.route("/api/register/status")
@role_required("admin")
def register_status():
    return jsonify(running=reg_camera.running, face_count=reg_camera.get_face_count())


@app.route("/video_feed_register")
@role_required("admin")
def video_feed_register():
    return Response(_mjpeg_generator(reg_camera.get_preview_frame),
                     mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/api/register/capture", methods=["POST"])
@role_required("admin")
@csrf.exempt
def register_capture():
    name = request.form.get("name", "").strip()
    identifier = request.form.get("identifier", "").strip()
    organization = request.form.get("organization", "").strip()
    consent_given = request.form.get("consent") == "true"

    if not name or not identifier:
        return jsonify(success=False, message="Name and ID are required."), 400
    if not consent_given:
        return jsonify(success=False, message="Consent is required before registering a person's face."), 400
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
                            embedding=encodings[0], photo_path=photo_path, consent_given=True)
    if person_id:
        for controller in live_controllers.values():
            controller.refresh_known_persons()
        log_audit(session["user"]["username"], "PERSON_REGISTERED", f"name={name}, id={identifier}")
        return jsonify(success=True, person_id=person_id)
    return jsonify(success=False, message="Database error — could not save."), 500


# ---------------------------------------------------------
# Logs — any logged-in role
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


# ---------------------------------------------------------
# Settings — admin only
# ---------------------------------------------------------
@app.route("/settings", methods=["GET", "POST"])
@role_required("admin")
def settings_page():
    saved = False
    if request.method == "POST":
        cameras = []
        for i in range(1, 4):
            name = request.form.get(f"cam{i}_name", "").strip()
            source = request.form.get(f"cam{i}_source", "").strip()
            if name and source:
                source_value = int(source) if source.isdigit() else source
                cameras.append({"id": f"cam{i}", "name": name, "source": source_value})

        new_values = {
            "CAMERAS": cameras if cameras else app_config.CAMERAS,
            "FACE_MATCH_TOLERANCE": float(request.form.get("face_match_tolerance", app_config.FACE_MATCH_TOLERANCE)),
            "EXIT_TIMEOUT_SECONDS": int(request.form.get("exit_timeout", app_config.EXIT_TIMEOUT_SECONDS)),
            "LOG_COOLDOWN_SECONDS": int(request.form.get("log_cooldown", app_config.LOG_COOLDOWN_SECONDS)),
            "PROCESS_EVERY_N_FRAMES": int(request.form.get("process_every_n", app_config.PROCESS_EVERY_N_FRAMES)),
            "ENABLE_LIVENESS_CHECK": request.form.get("enable_liveness") == "on",
            "LIVENESS_EAR_THRESHOLD": float(request.form.get("liveness_ear", app_config.LIVENESS_EAR_THRESHOLD)),
            "LIVENESS_TIMEOUT_SECONDS": int(request.form.get("liveness_timeout", app_config.LIVENESS_TIMEOUT_SECONDS)),
            "REPEAT_OFFENDER_THRESHOLD": int(request.form.get("repeat_threshold", app_config.REPEAT_OFFENDER_THRESHOLD)),
            "ENABLE_ALERT_SOUND": request.form.get("enable_alert_sound") == "on",
            "ALERT_COOLDOWN_SECONDS": int(request.form.get("alert_cooldown", app_config.ALERT_COOLDOWN_SECONDS)),
            "RETENTION_DAYS": int(request.form.get("retention_days", app_config.RETENTION_DAYS)),
        }
        app_config.save_settings(new_values)
        logger.info(f"Settings updated via web UI by '{session['user']['username']}'.")
        log_audit(session["user"]["username"], "SETTINGS_UPDATED", "")
        saved = True

    current = app_config.get_current_settings()
    return render_template("settings.html", s=current, saved=saved)


@app.route("/api/purge", methods=["POST"])
@role_required("admin")
@csrf.exempt
def api_purge():
    days = int(request.form.get("days", RETENTION_DAYS))
    result = purge_old_data(days)
    log_audit(session["user"]["username"], "DATA_PURGED", f"retention_days={days}, {result}")
    return jsonify(success=True, **result)


@app.route("/audit")
@role_required("admin")
def audit_page():
    return render_template("audit.html", entries=get_audit_log(limit=200))


# ---------------------------------------------------------
# Health check
# ---------------------------------------------------------
@app.route("/api/health")
@login_required
def api_health():
    from health_check import run_health_check
    results = run_health_check()
    overall_ok = all(r["ok"] for r in results[:4])
    return jsonify(overall_ok=overall_ok, checks=results)


@app.route("/health")
@login_required
def health_page():
    return render_template("health.html")


if __name__ == "__main__":
    from health_check import run_health_check, print_health_report
    print_health_report(run_health_check())

    protocol = "https" if ENABLE_HTTPS else "http"
    logger.info(f"Starting web app at {protocol}://127.0.0.1:5000")
    if ENABLE_HTTPS:
        logger.info("HTTPS is self-signed — your browser will show a security warning; this is expected for local use.")

    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True,
            ssl_context="adhoc" if ENABLE_HTTPS else None)