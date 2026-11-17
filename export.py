"""Export helpers (CSV, XLSX, PDF). Only result data and the disclaimer are written.
Search history, audio and identifiers are never included."""
from __future__ import annotations

import csv
import io
from datetime import datetime
from decimal import Decimal

from fpdf import FPDF
from openpyxl import Workbook

from core.engine import DATASET_VERSION, DISCLAIMER, gst_split, outcome_label, pct_text, total_pct


def _stamp() -> str:
    return datetime.now().strftime("%d %b %Y %H:%M")


def build_rows(records: list[dict], supply: str) -> list[dict]:
    rows = []
    for r in records:
        split = gst_split(Decimal(r["central_pct"]), supply)
        rows.append({
            "Item": r["description"],
            "HSN/SAC": r["code"],
            "Type": "Goods" if r["kind"] == "goods" else "Service",
            "Status": outcome_label(r),
            "Total GST %": pct_text(total_pct(r)),
            "CGST %": pct_text(split["cgst_pct"]),
            "SGST/UTGST %": pct_text(split["sgst_pct"]),
            "IGST %": pct_text(split["igst_pct"]),
            "Condition": r["condition"] or "None",
            "Notification": r["notification"],
            "Effective from": r["effective_from"],
            "Source": r["source_url"],
            "Dataset version": DATASET_VERSION,
            "Downloaded": _stamp(),
        })
    return rows


def to_csv(rows: list[dict]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    if rows:
        writer.writerow(list(rows[0].keys()))
        for row in rows:
            writer.writerow(list(row.values()))
    writer.writerow([])
    writer.writerow(["Disclaimer", DISCLAIMER])
    return buf.getvalue().encode("utf-8-sig")


def to_xlsx(rows: list[dict]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Results"
    if rows:
        ws.append(list(rows[0].keys()))
        for row in rows:
            ws.append(list(row.values()))
    notes = wb.create_sheet("Notes")
    notes.append(["Disclaimer", DISCLAIMER])
    notes.append(["Dataset version", DATASET_VERSION])
    notes.append(["Downloaded", _stamp()])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _pdf_text(text: str) -> str:
    """FPDF's built-in fonts cover Latin-1 only, so swap a few symbols and replace the rest."""
    for src, dst in {"—": "-", "–": "-", "·": "|", "₹": "Rs."}.items():
        text = text.replace(src, dst)
    return text.encode("latin-1", "replace").decode("latin-1")


def to_pdf(title: str, rows: list[dict]) -> bytes:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    pdf.multi_cell(0, 8, _pdf_text(title), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.multi_cell(0, 5, _pdf_text(f"Dataset: {DATASET_VERSION} | Downloaded: {_stamp()}"),
                   new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    for number, row in enumerate(rows, start=1):
        pdf.set_font("Helvetica", "B", 10)
        pdf.multi_cell(0, 6, _pdf_text(f"{number}. {row.get('Item', 'Calculation')}"),
                       new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 9)
        for key, value in row.items():
            if key == "Item":
                continue
            pdf.multi_cell(0, 5, _pdf_text(f"   {key}: {value}"), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
    pdf.set_font("Helvetica", "I", 8)
    pdf.multi_cell(0, 4, _pdf_text(DISCLAIMER), new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())
