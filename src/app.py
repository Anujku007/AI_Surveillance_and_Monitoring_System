"""
app.py
Unified front-end for the AI Surveillance System — replaces running
main.py / register_faces.py / dashboard.py as separate scripts.

Tabs:
    1. Live Monitoring — embedded camera feed with detection/recognition
    2. Register Person — embedded camera preview to register new people
       (only reachable after admin login, so registration is effectively
       restricted to the authenticated admin/user)
    3. All Events       — raw event log
    4. Sessions          — paired Entry/Exit view

Usage:
    python app.py
"""

import os
import cv2
import subprocess
import platform
from datetime import datetime

import tkinter as tk
from tkinter import ttk, messagebox

try:
    from PIL import Image, ImageTk
except ImportError:
    raise SystemExit("Pillow is required. Install it with:\n    pip install pillow")

from config import KNOWN_FACES_DIR
from database import init_db, get_all_logs, add_person
from error_handler import logger
from report_generator import generate_pdf_report
from live_feed import LiveFeedController
from registration_panel import RegistrationCamera
from encoder import FaceEncoder
from dashboard import show_login, build_sessions   # reused, not duplicated

THUMBNAIL_SIZE = (220, 220)


class UnifiedApp:
    def __init__(self, root):
        self.root = root
        self.root.title("AI Surveillance System — Control Center")
        self.root.geometry("1200x700")
        self.root.minsize(1000, 600)

        self.live_controller = LiveFeedController()
        self.reg_camera = RegistrationCamera()
        self.reg_encoder = FaceEncoder()

        self.live_photo_ref = None
        self.reg_photo_ref = None
        self.current_thumbnail = None
        self._events_snapshot_map = {}
        self._sessions_snapshot_map = {}

        self._build_ui()
        self.refresh_logs()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # -----------------------------------------------------
    # Top-level layout
    # -----------------------------------------------------
    def _build_ui(self):
        top_bar = tk.Frame(self.root, pady=8, padx=10)
        top_bar.pack(fill="x")
        tk.Label(top_bar, text="AI Surveillance System", font=("Segoe UI", 14, "bold")).pack(side="left")
        tk.Button(top_bar, text="Generate PDF Report", command=self.generate_report,
                  bg="#2c6ed5", fg="white").pack(side="right", padx=(0, 8))
        tk.Button(top_bar, text="Refresh Logs", command=self.refresh_logs).pack(side="right")

        body = tk.Frame(self.root)
        body.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        notebook_frame = tk.Frame(body)
        notebook_frame.pack(side="left", fill="both", expand=True)
        self.notebook = ttk.Notebook(notebook_frame)
        self.notebook.pack(fill="both", expand=True)

        live_tab = tk.Frame(self.notebook)
        register_tab = tk.Frame(self.notebook)
        events_tab = tk.Frame(self.notebook)
        sessions_tab = tk.Frame(self.notebook)
        self.notebook.add(live_tab, text="Live Monitoring")
        self.notebook.add(register_tab, text="Register Person")
        self.notebook.add(events_tab, text="All Events")
        self.notebook.add(sessions_tab, text="Sessions (Entry + Exit)")

        self._build_live_tab(live_tab)
        self._build_register_tab(register_tab)
        self.events_tree = self._build_events_table(events_tab)
        self.sessions_tree = self._build_sessions_table(sessions_tab)

        # Shared thumbnail panel (used by Events/Sessions tab selections)
        thumb_frame = tk.Frame(body, width=240, relief="groove", borderwidth=1)
        thumb_frame.pack(side="right", fill="y", padx=(10, 0))
        thumb_frame.pack_propagate(False)
        tk.Label(thumb_frame, text="Snapshot", font=("Segoe UI", 11, "bold")).pack(pady=(10, 5))
        self.thumb_label = tk.Label(thumb_frame, text="Select a log row\nto view snapshot",
                                     width=28, height=14, bg="#f5f5f5", relief="sunken")
        self.thumb_label.pack(padx=10, pady=5)
        self.detail_label = tk.Label(thumb_frame, text="", justify="left",
                                      font=("Segoe UI", 9), wraplength=220)
        self.detail_label.pack(padx=10, pady=10, anchor="w")

        self.status_var = tk.StringVar(value="Ready")
        tk.Label(self.root, textvariable=self.status_var, bd=1, relief="sunken", anchor="w").pack(
            fill="x", side="bottom")

    # -----------------------------------------------------
    # Live Monitoring tab
    # -----------------------------------------------------
    def _build_live_tab(self, parent):
        control_frame = tk.Frame(parent, pady=8)
        control_frame.pack(fill="x")

        self.live_start_btn = tk.Button(control_frame, text="Start Monitoring",
                                         command=self.start_live, bg="#2c9e4c", fg="white", width=16)
        self.live_start_btn.pack(side="left", padx=(0, 6))
        self.live_stop_btn = tk.Button(control_frame, text="Stop Monitoring",
                                        command=self.stop_live, bg="#c0392b", fg="white",
                                        width=16, state="disabled")
        self.live_stop_btn.pack(side="left")

        self.live_stats_var = tk.StringVar(value="Camera not started")
        tk.Label(control_frame, textvariable=self.live_stats_var, font=("Segoe UI", 9)).pack(
            side="left", padx=20)

        self.live_video_label = tk.Label(parent, bg="black", text="Camera feed will appear here",
                                          fg="white")
        self.live_video_label.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def start_live(self):
        if self.reg_camera.running:
            messagebox.showwarning("Camera In Use", "Please stop the registration camera preview first.")
            return
        if self.live_controller.start():
            self.live_start_btn.config(state="disabled")
            self.live_stop_btn.config(state="normal")
            self._update_live_frame()
        else:
            messagebox.showerror("Error", "Could not start camera. Check that it's connected and not in use.")

    def stop_live(self):
        self.live_controller.stop()
        self.live_start_btn.config(state="normal")
        self.live_stop_btn.config(state="disabled")
        self.live_video_label.config(image="", text="Camera feed will appear here")
        self.live_photo_ref = None
        self.live_stats_var.set("Camera not started")
        self.refresh_logs()

    def _update_live_frame(self):
        if not self.live_controller.running:
            return
        frame = self.live_controller.get_latest_frame()
        if frame is not None:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(rgb)
            img.thumbnail((900, 560))
            photo = ImageTk.PhotoImage(img)
            self.live_video_label.config(image=photo, text="")
            self.live_photo_ref = photo

            s = self.live_controller.get_stats()
            self.live_stats_var.set(
                f"FPS: {s['fps']:.1f}  |  Faces: {s['faces']}  |  "
                f"Known: {s['known']}  Unknown: {s['unknown']}  "
                f"Spoof: {s['spoof']}  Repeat: {s['repeat']}"
            )
        self.root.after(30, self._update_live_frame)

    # -----------------------------------------------------
    # Register Person tab
    # -----------------------------------------------------
    def _build_register_tab(self, parent):
        form_frame = tk.Frame(parent, pady=10, padx=10)
        form_frame.pack(fill="x")

        tk.Label(form_frame, text="Name:").grid(row=0, column=0, sticky="w", pady=4)
        self.reg_name_var = tk.StringVar()
        tk.Entry(form_frame, textvariable=self.reg_name_var, width=30).grid(row=0, column=1, sticky="w")

        tk.Label(form_frame, text="ID / Roll No.:").grid(row=1, column=0, sticky="w", pady=4)
        self.reg_id_var = tk.StringVar()
        tk.Entry(form_frame, textvariable=self.reg_id_var, width=30).grid(row=1, column=1, sticky="w")

        tk.Label(form_frame, text="Organization:").grid(row=2, column=0, sticky="w", pady=4)
        self.reg_org_var = tk.StringVar()
        tk.Entry(form_frame, textvariable=self.reg_org_var, width=30).grid(row=2, column=1, sticky="w")

        btn_frame = tk.Frame(parent, pady=6, padx=10)
        btn_frame.pack(fill="x")
        self.reg_start_btn = tk.Button(btn_frame, text="Start Camera Preview",
                                        command=self.start_reg_camera, bg="#2c6ed5", fg="white")
        self.reg_start_btn.pack(side="left", padx=(0, 6))
        self.reg_capture_btn = tk.Button(btn_frame, text="Capture && Register",
                                          command=self.capture_and_register, bg="#2c9e4c",
                                          fg="white", state="disabled")
        self.reg_capture_btn.pack(side="left", padx=(0, 6))
        self.reg_stop_btn = tk.Button(btn_frame, text="Stop Preview",
                                       command=self.stop_reg_camera, bg="#c0392b", fg="white",
                                       state="disabled")
        self.reg_stop_btn.pack(side="left")

        self.reg_status_var = tk.StringVar(value="Camera not started")
        tk.Label(parent, textvariable=self.reg_status_var, font=("Segoe UI", 9)).pack(
            anchor="w", padx=10)

        self.reg_video_label = tk.Label(parent, bg="black", text="Registration camera preview",
                                         fg="white")
        self.reg_video_label.pack(fill="both", expand=True, padx=10, pady=(6, 10))

    def start_reg_camera(self):
        if self.live_controller.running:
            messagebox.showwarning("Camera In Use", "Please stop Live Monitoring first.")
            return
        if not self.reg_name_var.get().strip() or not self.reg_id_var.get().strip():
            messagebox.showwarning("Missing Info", "Enter at least Name and ID before starting the camera.")
            return
        if self.reg_camera.start():
            self.reg_start_btn.config(state="disabled")
            self.reg_capture_btn.config(state="normal")
            self.reg_stop_btn.config(state="normal")
            self._update_reg_frame()
        else:
            messagebox.showerror("Error", "Could not start camera.")

    def stop_reg_camera(self):
        self.reg_camera.stop()
        self.reg_start_btn.config(state="normal")
        self.reg_capture_btn.config(state="disabled")
        self.reg_stop_btn.config(state="disabled")
        self.reg_video_label.config(image="", text="Registration camera preview")
        self.reg_photo_ref = None
        self.reg_status_var.set("Camera not started")

    def _update_reg_frame(self):
        if not self.reg_camera.running:
            return
        frame = self.reg_camera.get_preview_frame()
        if frame is not None:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(rgb)
            img.thumbnail((700, 500))
            photo = ImageTk.PhotoImage(img)
            self.reg_video_label.config(image=photo, text="")
            self.reg_photo_ref = photo

            count = self.reg_camera.get_face_count()
            if count == 1:
                self.reg_status_var.set("1 face detected — ready to capture")
            elif count == 0:
                self.reg_status_var.set("No face detected")
            else:
                self.reg_status_var.set(f"{count} faces detected — only one person should be in frame")
        self.root.after(30, self._update_reg_frame)

    def capture_and_register(self):
        name = self.reg_name_var.get().strip()
        identifier = self.reg_id_var.get().strip()
        organization = self.reg_org_var.get().strip()
        if not name or not identifier:
            messagebox.showwarning("Missing Info", "Name and ID are required.")
            return
        if self.reg_camera.get_face_count() != 1:
            messagebox.showwarning("Capture Failed", "Exactly one face must be visible to register.")
            return

        raw_frame = self.reg_camera.capture_raw_frame()
        if raw_frame is None:
            messagebox.showerror("Error", "No frame available to capture.")
            return

        boxes = self.reg_camera.detector.detect(raw_frame)
        if len(boxes) != 1:
            messagebox.showwarning("Capture Failed", "Face detection changed — please try again.")
            return

        encodings = self.reg_encoder.encode_faces(raw_frame, boxes)
        if not encodings:
            messagebox.showerror("Error", "Could not generate face embedding.")
            return

        os.makedirs(KNOWN_FACES_DIR, exist_ok=True)
        safe_name = name.replace(" ", "_").lower()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        photo_path = os.path.join(KNOWN_FACES_DIR, f"{safe_name}_{timestamp}.jpg")
        cv2.imwrite(photo_path, raw_frame)

        person_id = add_person(name=name, identifier=identifier, organization=organization,
                                embedding=encodings[0], photo_path=photo_path)

        if person_id:
            messagebox.showinfo("Success", f"Registered '{name}' successfully (ID: {identifier}).")
            self.reg_name_var.set("")
            self.reg_id_var.set("")
            self.reg_org_var.set("")
            self.stop_reg_camera()
            self.live_controller.refresh_known_persons()
        else:
            messagebox.showerror("Error", "Registration failed — could not save to database.")

    # -----------------------------------------------------
    # Events / Sessions tables (same pattern as dashboard.py)
    # -----------------------------------------------------
    def _build_events_table(self, parent):
        columns = ("id", "name", "identifier", "event", "time", "location", "flag")
        tree = ttk.Treeview(parent, columns=columns, show="headings", height=18)
        headings = {"id": "Log ID", "name": "Name", "identifier": "ID No.", "event": "Event",
                    "time": "Timestamp", "location": "Location", "flag": "Status"}
        widths = {"id": 60, "name": 140, "identifier": 70, "event": 70,
                  "time": 150, "location": 110, "flag": 100}
        for col in columns:
            tree.heading(col, text=headings[col])
            tree.column(col, width=widths[col], anchor="center")

        tree.tag_configure("suspicious", background="#ffe0e0")
        tree.tag_configure("known_entry", background="#e0ffe0")
        tree.tag_configure("known_exit", background="#f0f0f0")

        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        tree.bind("<<TreeviewSelect>>", self._on_event_selected)
        return tree

    def _build_sessions_table(self, parent):
        columns = ("id", "name", "identifier", "entry", "exit", "duration", "location", "flag")
        tree = ttk.Treeview(parent, columns=columns, show="headings", height=18)
        headings = {"id": "Log ID", "name": "Name", "identifier": "ID No.", "entry": "Entry Time",
                    "exit": "Exit Time", "duration": "Duration", "location": "Location", "flag": "Status"}
        widths = {"id": 60, "name": 130, "identifier": 65, "entry": 145, "exit": 145,
                  "duration": 85, "location": 105, "flag": 90}
        for col in columns:
            tree.heading(col, text=headings[col])
            tree.column(col, width=widths[col], anchor="center")

        tree.tag_configure("suspicious", background="#ffe0e0")
        tree.tag_configure("present", background="#fff6cc")
        tree.tag_configure("known", background="#e0ffe0")

        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        tree.bind("<<TreeviewSelect>>", self._on_session_selected)
        return tree

    def refresh_logs(self):
        try:
            logs = get_all_logs(limit=500)
        except Exception as e:
            logger.error(f"Could not load logs: {e}")
            self.status_var.set(f"Error loading logs: {e}")
            return
        self._populate_events(logs)
        self._populate_sessions(logs)
        self.status_var.set(f"Loaded {len(logs)} events.")

    def _populate_events(self, logs):
        for row in self.events_tree.get_children():
            self.events_tree.delete(row)
        self._events_snapshot_map = {}

        for log in logs:
            name = log["name"] or "Unknown"
            identifier = log["identifier"] or "-"
            status = "SUSPICIOUS" if log["is_suspicious"] else "Authorized"
            time_str = log["timestamp"].replace("T", "  ")[:19]

            if log["is_suspicious"]:
                tag = "suspicious"
            elif log["event_type"] == "ENTRY":
                tag = "known_entry"
            else:
                tag = "known_exit"

            self.events_tree.insert("", "end", iid=str(log["log_id"]), values=(
                log["log_id"], name, identifier, log["event_type"],
                time_str, log["camera_location"], status
            ), tags=(tag,))
            self._events_snapshot_map[log["log_id"]] = log["snapshot_path"]

    def _populate_sessions(self, logs):
        for row in self.sessions_tree.get_children():
            self.sessions_tree.delete(row)
        self._sessions_snapshot_map = {}

        sessions = build_sessions(logs)
        for i, s in enumerate(sessions):
            entry_str = s["entry_time"].replace("T", "  ")[:19] if s["entry_time"] else "-"
            exit_str = s["exit_time"].replace("T", "  ")[:19] if s["exit_time"] else "-"
            status = "SUSPICIOUS" if s["is_suspicious"] else "Authorized"

            if s["is_suspicious"]:
                tag = "suspicious"
            elif s["still_present"]:
                tag = "present"
            else:
                tag = "known"

            row_id = str(i)
            self.sessions_tree.insert("", "end", iid=row_id, values=(
                s["log_id"], s["name"], s["identifier"], entry_str, exit_str,
                s["duration_str"], s["location"], status
            ), tags=(tag,))
            self._sessions_snapshot_map[row_id] = s["entry_snapshot"]

    def _on_event_selected(self, event):
        selection = self.events_tree.selection()
        if not selection:
            return
        log_id = int(selection[0])
        values = self.events_tree.item(selection[0], "values")
        detail_text = (
            f"Log ID: {values[0]}\nName: {values[1]}\nID No.: {values[2]}\n"
            f"Event: {values[3]}\nTime: {values[4]}\n"
            f"Location: {values[5]}\nStatus: {values[6]}"
        )
        self.detail_label.config(text=detail_text)
        self._load_thumbnail(self._events_snapshot_map.get(log_id))

    def _on_session_selected(self, event):
        selection = self.sessions_tree.selection()
        if not selection:
            return
        row_id = selection[0]
        values = self.sessions_tree.item(row_id, "values")
        detail_text = (
            f"Log ID: {values[0]}\nName: {values[1]}\nID No.: {values[2]}\n"
            f"Entry: {values[3]}\nExit: {values[4]}\n"
            f"Duration: {values[5]}\nLocation: {values[6]}\nStatus: {values[7]}"
        )
        self.detail_label.config(text=detail_text)
        self._load_thumbnail(self._sessions_snapshot_map.get(row_id))

    def _load_thumbnail(self, path):
        if not path or not os.path.exists(path):
            self.thumb_label.config(image="", text="No snapshot\navailable")
            self.current_thumbnail = None
            return
        try:
            img = Image.open(path)
            img.thumbnail(THUMBNAIL_SIZE)
            photo = ImageTk.PhotoImage(img)
            self.thumb_label.config(image=photo, text="")
            self.current_thumbnail = photo
        except Exception as e:
            logger.warning(f"Could not load snapshot thumbnail: {e}")
            self.thumb_label.config(image="", text="Could not load\nimage")
            self.current_thumbnail = None

    # -----------------------------------------------------
    # PDF report
    # -----------------------------------------------------
    def generate_report(self):
        try:
            self.status_var.set("Generating PDF report...")
            self.root.update_idletasks()
            path = generate_pdf_report()
            self.status_var.set(f"Report saved: {path}")
            if messagebox.askyesno("Report Generated", f"PDF report saved to:\n{path}\n\nOpen it now?"):
                self._open_file(path)
        except Exception as e:
            logger.error(f"Could not generate report: {e}")
            messagebox.showerror("Error", f"Could not generate report:\n{e}")
            self.status_var.set("Report generation failed.")

    @staticmethod
    def _open_file(path):
        try:
            if platform.system() == "Windows":
                os.startfile(path)
            elif platform.system() == "Darwin":
                subprocess.run(["open", path])
            else:
                subprocess.run(["xdg-open", path])
        except Exception as e:
            logger.warning(f"Could not auto-open file: {e}")

    # -----------------------------------------------------
    # Shutdown
    # -----------------------------------------------------
    def _on_close(self):
        self.live_controller.stop()
        self.reg_camera.stop()
        self.root.destroy()


def main():
    if not show_login():
        logger.info("Login cancelled or failed. App not opened.")
        return

    init_db()
    root = tk.Tk()
    app = UnifiedApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()