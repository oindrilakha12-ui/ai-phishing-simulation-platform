"""CSV and PDF exports (reportlab; no system libraries required)."""
from __future__ import annotations

import csv
import html
import io
from datetime import datetime
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

SYNTHETIC_NOTE = "All figures are generated from SYNTHETIC simulation data for training purposes."


def _csv_safe(value: Any) -> Any:
    """Neutralise CSV/formula injection: cells starting with = + - @ are prefixed with a quote."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def rows_to_csv(rows: list[dict[str, Any]], columns: list[str]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow({k: _csv_safe(r.get(k)) for k in columns})
    return buf.getvalue()


def analytics_csv(data: dict[str, Any], org_name: str) -> str:
    k = data["kpis"]
    buf = io.StringIO()
    buf.write(f"# PhishGuard analytics export - {_csv_safe(org_name)} - {datetime.now():%Y-%m-%d %H:%M}\n")
    buf.write(f"# {SYNTHETIC_NOTE}\n")
    buf.write("metric,value\n")
    for key in ("recipients", "clicked", "reported", "click_rate", "report_rate", "report_to_click_ratio",
                "completion_rate", "time_to_report_median_min", "time_to_report_p90_min"):
        buf.write(f"{key},{k.get(key)}\n")
    buf.write("\n")
    buf.write(rows_to_csv(data["departments"], ["department", "recipients", "clicked", "reported",
                                                "click_rate", "report_rate"]))
    return buf.getvalue()


def _pdf_table(rows: list[list[Any]]) -> Table:
    t = Table(rows, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a8a")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
    ]))
    return t


def analytics_pdf(data: dict[str, Any], org_name: str, risk_departments: list[dict[str, Any]]) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title="PhishGuard compliance report",
                            leftMargin=1.6 * cm, rightMargin=1.6 * cm)
    ss = getSampleStyleSheet()
    k = data["kpis"]
    pct = lambda v: "-" if v is None else f"{v * 100:.1f}%"  # noqa: E731
    story = [
        Paragraph("PhishGuard â€” Security-Awareness Compliance Report", ss["Title"]),
        Paragraph(f"Organization: <b>{html.escape(org_name)}</b> &nbsp; Generated: {datetime.now():%Y-%m-%d %H:%M}", ss["Normal"]),
        Paragraph(f"<i>{SYNTHETIC_NOTE}</i>", ss["Normal"]),
        Spacer(1, 12),
        Paragraph("Key indicators", ss["Heading2"]),
        _pdf_table([
            ["Recipients", "Click rate", "Report rate", "Report:click", "Training completion", "Median time-to-report"],
            [k["recipients"], pct(k["click_rate"]), pct(k["report_rate"]), k["report_to_click_ratio"] or "-",
             pct(k["completion_rate"]),
             "-" if k["time_to_report_median_min"] is None else f"{k['time_to_report_median_min']} min"],
        ]),
        Spacer(1, 12),
        Paragraph("Departments", ss["Heading2"]),
        _pdf_table([["Department", "Recipients", "Click rate", "Report rate"]] + [
            [d["department"], d["recipients"], pct(d["click_rate"]), pct(d["report_rate"])]
            for d in data["departments"]]),
        Spacer(1, 12),
        Paragraph("Department risk", ss["Heading2"]),
        _pdf_table([["Department", "Risk score", "Level", "People", "High-risk people"]] + [
            [d["department"], d["score"], d["level"], d["people"], d["high_risk_people"]] for d in risk_departments]),
        Spacer(1, 12),
        Paragraph("Most-missed red-flag categories", ss["Heading2"]),
        _pdf_table([["Category", "Simulated clicks"]] + [[r["category"], r["count"]]
                                                          for r in data["top_failed_flags"][:8]]),
    ]
    doc.build(story)
    return buf.getvalue()


def certificate_pdf(learner: str, module: str, serial: str, issued: datetime, org_name: str) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), title="Certificate of completion")
    ss = getSampleStyleSheet()
    story = [
        Spacer(1, 2 * cm),
        Paragraph("Certificate of Completion", ss["Title"]),
        Spacer(1, 0.8 * cm),
        Paragraph(f"This certifies that <b>{html.escape(learner)}</b>", ss["Heading2"]),
        Paragraph(f"has completed the security-awareness module <b>{html.escape(module)}</b>", ss["Heading3"]),
        Spacer(1, 0.6 * cm),
        Paragraph(f"{org_name} Â· Issued {issued:%d %B %Y} Â· Serial {serial}", ss["Normal"]),
        Spacer(1, 0.4 * cm),
        Paragraph("<i>Issued by PhishGuard, a training platform. Learners in this demo are synthetic.</i>",
                  ss["Normal"]),
    ]
    doc.build(story)
    return buf.getvalue()
