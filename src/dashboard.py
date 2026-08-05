"""
dashboard.py
GUI dashboard to view entry/exit logs with photo thumbnails.

Two views (tabs):
    1. All Events    - every ENTRY/EXIT row separately, most recent first
    2. Sessions       - ENTRY and EXIT paired into a single row per visit

Usage:
    python dashboard.py
"""

import tkinter as tk
from tkinter import ttk
import os
from datetime import datetime

try:
    from PIL import Image, ImageTk
except ImportError:
    raise SystemExit(
        "Pillow is required for the dashboard. Install it with:\n"
        "    pip install pillow"
    )

from database import init_db, get_all_logs
from error_handler import logger


THUMBNAIL_SIZE = (220, 220)


def _parse_ts(ts_str):
    return datetime.fromisoformat(ts_str)


def build_sessions(logs):
    """
    Pairs ENTRY -> EXIT events into single 'session' rows per person/unknown bucket.
    `logs` should be a list of log dicts (any order) as returned by get_all_logs().

    Returns a list of session dicts, most recent first:
        {name, identifier, is_suspicious, entry_time, exit_time,
         duration_str, entry_snapshot, still_present}
    """
    # Process in chronological order (oldest first) so ENTRY always comes before its EXIT
    ordered = sorted(logs, key=lambda l: l["timestamp"])

    open_sessions = {}  # key -> session dict currently waiting for an EXIT
    sessions = []

    for log in ordered:
        key = log["identifier"] if log["identifier"] else "unknown"
        # separate unknown sessions loosely by day so they don't merge across long gaps
        if key == "unknown":
            key = f"unknown_{log['timestamp'][:10]}"

        if log["event_type"] == "ENTRY":
            open_sessions[key] = {
                "log_id": log["log_id"],
                "name": log["name"] or "Unknown",
                "identifier": log["identifier"] or "-",
                "is_suspicious": bool(log["is_suspicious"]),
                "entry_time": log["timestamp"],
                "exit_time": None,
                "location": log["camera_location"],
                "entry_snapshot": log["snapshot_path"],
                "still_present": True,
            }
            sessions.append(open_sessions[key])

        elif log["event_type"] == "EXIT":
            session = open_sessions.get(key)
            if session and session["still_present"]:
                session["exit_time"] = log["timestamp"]
                session["still_present"] = False
            else:
                # EXIT with no matching open ENTRY (e.g. system restarted) —
                # still show it as its own row so nothing is silently dropped
                sessions.append({
                    "log_id": log["log_id"],
                    "name": log["name"] or "Unknown",
                    "identifier": log["identifier"] or "-",
                    "is_suspicious": bool(log["is_suspicious"]),
                    "entry_time": None,
                    "exit_time": log["timestamp"],
                    "location": log["camera_location"],
                    "entry_snapshot": log["snapshot_path"],
                    "still_present": False,
                })

    # Compute duration strings
    for s in sessions:
        if s["entry_time"] and s["exit_time"]:
            delta = _parse_ts(s["exit_time"]) - _parse_ts(s["entry_time"])
            total_seconds = int(delta.total_seconds())
            mins, secs = divmod(total_seconds, 60)
            s["duration_str"] = f"{mins}m {secs}s"
        elif s["entry_time"] and not s["exit_time"]:
            s["duration_str"] = "Still inside"
        else:
            s["duration_str"] = "-"

    sessions.sort(key=lambda s: s["entry_time"] or s["exit_time"], reverse=True)
    return sessions


class DashboardApp:
    def __init__(self, root):
        self.root = root
        self.root.title("AI Surveillance System — Log Dashboard")
        self.root.geometry("1100x540")
        self.root.minsize(850, 420)

        self.current_thumbnail = None
        self._events_snapshot_map = {}
        self._sessions_snapshot_map = {}

        self._build_ui()
        self.refresh_logs()

    # -----------------------------------------------------
    # UI layout
    # -----------------------------------------------------
    def _build_ui(self):
        top_bar = tk.Frame(self.root, pady=8, padx=10)
        top_bar.pack(fill="x")
        tk.Label(top_bar, text="Surveillance Logs", font=("Segoe UI", 14, "bold")).pack(side="left")
        tk.Button(top_bar, text="Refresh", command=self.refresh_logs).pack(side="right")

        body = tk.Frame(self.root)
        body.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # --- Notebook (tabs) on the left ---
        notebook_frame = tk.Frame(body)
        notebook_frame.pack(side="left", fill="both", expand=True)

        self.notebook = ttk.Notebook(notebook_frame)
        self.notebook.pack(fill="both", expand=True)

        events_tab = tk.Frame(self.notebook)
        sessions_tab = tk.Frame(self.notebook)
        self.notebook.add(events_tab, text="All Events")
        self.notebook.add(sessions_tab, text="Sessions (Entry + Exit)")

        self.events_tree = self._build_events_table(events_tab)
        self.sessions_tree = self._build_sessions_table(sessions_tab)

        # --- Shared thumbnail panel on the right ---
        thumb_frame = tk.Frame(body, width=240, relief="groove", borderwidth=1)
        thumb_frame.pack(side="right", fill="y", padx=(10, 0))
        thumb_frame.pack_propagate(False)

        tk.Label(thumb_frame, text="Snapshot", font=("Segoe UI", 11, "bold")).pack(pady=(10, 5))
        self.thumb_label = tk.Label(thumb_frame, text="Select a row\nto view snapshot",
                                     width=28, height=14, bg="#f5f5f5", relief="sunken")
        self.thumb_label.pack(padx=10, pady=5)

        self.detail_label = tk.Label(thumb_frame, text="", justify="left",
                                      font=("Segoe UI", 9), wraplength=220)
        self.detail_label.pack(padx=10, pady=10, anchor="w")

        self.status_var = tk.StringVar(value="Ready")
        tk.Label(self.root, textvariable=self.status_var, bd=1, relief="sunken", anchor="w").pack(
            fill="x", side="bottom")

    def _build_events_table(self, parent):
        columns = ("id", "name", "identifier", "event", "time", "location", "flag")
        tree = ttk.Treeview(parent, columns=columns, show="headings", height=18)

        headings = {"id": "Log ID", "name": "Name", "identifier": "ID No.", "event": "Event",
                    "time": "Timestamp", "location": "Location", "flag": "Status"}
        widths = {"id": 60, "name": 150, "identifier": 80, "event": 70,
                  "time": 160, "location": 110, "flag": 100}
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
        widths = {"id": 60, "name": 140, "identifier": 70, "entry": 150, "exit": 150,
                  "duration": 90, "location": 110, "flag": 90}
        for col in columns:
            tree.heading(col, text=headings[col])
            tree.column(col, width=widths[col], anchor="center")

        tree.tag_configure("suspicious", background="#ffe0e0")
        tree.tag_configure("present", background="#fff6cc")   # still inside — highlight
        tree.tag_configure("known", background="#e0ffe0")

        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        tree.bind("<<TreeviewSelect>>", self._on_session_selected)
        return tree

    # -----------------------------------------------------
    # Data loading
    # -----------------------------------------------------
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

    # -----------------------------------------------------
    # Selection handlers
    # -----------------------------------------------------
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

    # -----------------------------------------------------
    # Thumbnail display
    # -----------------------------------------------------
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


def main():
    init_db()
    root = tk.Tk()
    app = DashboardApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()