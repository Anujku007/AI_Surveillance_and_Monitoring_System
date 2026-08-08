"""
report_generator.py
Generates a professional PDF report of surveillance logs — summary stats,
a full event table, and embedded snapshot images for suspicious/spoof events.

Usage:
    from report_generator import generate_pdf_report
    path = generate_pdf_report()   # generates into logs/reports/

    or standalone:
    python report_generator.py
"""

import os
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image as RLImage
)

from config import LOGS_DIR
from database import init_db, get_all_logs
from error_handler import logger, error_context

REPORTS_DIR = os.path.join(LOGS_DIR, "reports")
os.makedirs(REPORTS_DIR, exist_ok=True)

MAX_SNAPSHOT_IMAGES = 8  # cap embedded images so the PDF doesn't get huge


def _status_label(log):
    if log["is_suspicious"]:
        return "SUSPICIOUS"
    return "Authorized"


def _build_summary(logs):
    total = len(logs)
    authorized = sum(1 for l in logs if not l["is_suspicious"])
    suspicious = sum(1 for l in logs if l["is_suspicious"])
    entries = sum(1 for l in logs if l["event_type"] == "ENTRY")
    exits = sum(1 for l in logs if l["event_type"] == "EXIT")
    unique_known = len({l["identifier"] for l in logs if l["identifier"]})
    return {
        "total": total, "authorized": authorized, "suspicious": suspicious,
        "entries": entries, "exits": exits, "unique_known": unique_known
    }


def generate_pdf_report(output_path=None, limit=500):
    """
    Generates a PDF report of all (or up to `limit`) surveillance logs.
    Returns the path to the generated PDF.
    """
    with error_context("Generating PDF report"):
        init_db()
        logs = get_all_logs(limit=limit)

        if output_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = os.path.join(REPORTS_DIR, f"surveillance_report_{timestamp}.pdf")

        doc = SimpleDocTemplate(
            output_path, pagesize=A4,
            topMargin=0.6 * inch, bottomMargin=0.6 * inch,
            leftMargin=0.6 * inch, rightMargin=0.6 * inch
        )
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "TitleCustom", parent=styles["Title"], fontSize=18, spaceAfter=4
        )
        subtitle_style = ParagraphStyle(
            "Subtitle", parent=styles["Normal"], fontSize=10,
            textColor=colors.grey, spaceAfter=16
        )
        heading_style = ParagraphStyle(
            "HeadingCustom", parent=styles["Heading2"], spaceBefore=16, spaceAfter=8
        )

        elements = []

        # --- Title ---
        elements.append(Paragraph("AI Surveillance System — Activity Report", title_style))
        elements.append(Paragraph(
            f"Generated on {datetime.now().strftime('%d %B %Y, %I:%M %p')}",
            subtitle_style
        ))

        # --- Summary section ---
        summary = _build_summary(logs)
        elements.append(Paragraph("Summary", heading_style))

        summary_data = [
            ["Total Events", str(summary["total"])],
            ["Entries", str(summary["entries"])],
            ["Exits", str(summary["exits"])],
            ["Authorized Events", str(summary["authorized"])],
            ["Suspicious Events", str(summary["suspicious"])],
            ["Unique Registered Persons Seen", str(summary["unique_known"])],
        ]
        summary_table = Table(summary_data, colWidths=[3 * inch, 2 * inch])
        summary_table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dddddd")),
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f7f7f7")),
        ]))
        elements.append(summary_table)

        # --- Authorized events table ---
        authorized_logs = [l for l in logs if not l["is_suspicious"]]
        suspicious_logs_all = [l for l in logs if l["is_suspicious"]]

        elements.append(Paragraph(f"Authorized Events ({len(authorized_logs)})", heading_style))
        if authorized_logs:
            auth_data = [["Log ID", "Name", "ID No.", "Event", "Timestamp", "Location"]]
            for log in authorized_logs:
                auth_data.append([
                    str(log["log_id"]),
                    log["name"] or "-",
                    log["identifier"] or "-",
                    log["event_type"],
                    log["timestamp"].replace("T", " ")[:19],
                    log["camera_location"],
                ])
            auth_table = Table(auth_data, repeatRows=1, colWidths=[
                0.6 * inch, 1.3 * inch, 0.8 * inch, 0.7 * inch, 1.6 * inch, 1.3 * inch
            ])
            auth_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c6e2c")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#dddddd")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0fff0")]),
            ]))
            elements.append(auth_table)
        else:
            elements.append(Paragraph("No authorized events recorded.", styles["Normal"]))

        # --- Suspicious events table (separated, with reason) ---
        elements.append(Paragraph(f"Suspicious Events ({len(suspicious_logs_all)})", heading_style))
        if suspicious_logs_all:
            reason_labels = {
                "unknown_face": "Unknown Face",
                "spoof_suspected": "Spoof Suspected",
                "repeat_offender": "Repeat Offender",
            }
            susp_data = [["Log ID", "Name", "Event", "Timestamp", "Location", "Reason"]]
            for log in suspicious_logs_all:
                susp_data.append([
                    str(log["log_id"]),
                    log["name"] or "Unknown",
                    log["event_type"],
                    log["timestamp"].replace("T", " ")[:19],
                    log["camera_location"],
                    reason_labels.get(log["reason"], "Unknown Face"),
                ])
            susp_table = Table(susp_data, repeatRows=1, colWidths=[
                0.6 * inch, 1.2 * inch, 0.7 * inch, 1.6 * inch, 1.2 * inch, 1.1 * inch
            ])
            susp_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#a12020")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#dddddd")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#ffefef")]),
            ]))
            elements.append(susp_table)
        else:
            elements.append(Paragraph("No suspicious events recorded.", styles["Normal"]))

        # --- Snapshot images for suspicious events (capped) ---
        suspicious_logs = [l for l in suspicious_logs_all if l["snapshot_path"]
                            and os.path.exists(l["snapshot_path"])]
        if suspicious_logs:
            elements.append(Paragraph("Suspicious Event Snapshots", heading_style))
            for log in suspicious_logs[:MAX_SNAPSHOT_IMAGES]:
                caption = (f"Log ID {log['log_id']} — {log['name'] or 'Unknown'} — "
                           f"{log['event_type']} — {log['timestamp'].replace('T', ' ')[:19]}")
                elements.append(Paragraph(caption, styles["Normal"]))
                try:
                    img = RLImage(log["snapshot_path"], width=2.2 * inch, height=2.2 * inch)
                    elements.append(img)
                    elements.append(Spacer(1, 10))
                except Exception as e:
                    logger.warning(f"Could not embed snapshot for log_id={log['log_id']}: {e}")

            if len(suspicious_logs) > MAX_SNAPSHOT_IMAGES:
                elements.append(Paragraph(
                    f"...and {len(suspicious_logs) - MAX_SNAPSHOT_IMAGES} more suspicious "
                    f"event(s) not shown here (see full log table above).",
                    styles["Italic"]
                ))

        doc.build(elements)
        logger.info(f"PDF report generated: {output_path}")
        return output_path


if __name__ == "__main__":
    path = generate_pdf_report()
    print(f"Report saved to: {path}")