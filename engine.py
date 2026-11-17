"""Core logic for GST TAXORA: search, status labels, GST split and calculator.

Rates come only from data/gst_seed.csv. Nothing in this module invents a rate.
"""
from __future__ import annotations

import csv
import re
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

DATASET_VERSION = "seed-v1 (17 Nov 2026)"
DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "gst_seed.csv"
NOT_FOUND = "Item not found — please check spelling or try a related term."
NOT_FOUND_HELP = (
    "This version covers a limited list of goods and services. The item may be in the "
    "CBIC schedule but not yet in this app. Try its HSN or SAC code, or check the official notification."
)
SUGGESTION_NOTE = "Suggestions only — not a confirmed classification."
SIMILARITY_THRESHOLD = 0.20
TWO_DP = Decimal("0.01")

DISCLAIMER = (
    "This tool is provided for general information and educational purposes. "
    "GST classification and tax treatment depend on the precise nature of the goods or services, "
    "facts of the transaction, applicable notifications and conditions. Verify the relevant official "
    "notification and obtain advice from a qualified tax professional before relying on the result for "
    "invoicing, return filing or other compliance. The tool does not constitute legal or tax advice."
)

OUTCOME_TEXT = {
    "taxable": "GST APPLICABLE",
    "exempt": "GST NOT APPLICABLE (Exempt)",
    "nil": "GST NOT APPLICABLE (Nil rated)",
    "non_taxable": "NOT A TAXABLE SUPPLY",
    "zero_rated": "ZERO-RATED SUPPLY",
}


def normalise(text: str) -> str:
    text = re.sub(r"[^a-z0-9\s]", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def _to_decimal(value) -> Decimal:
    try:
        number = Decimal(str(value).strip())
    except Exception as exc:
        raise ValueError("Enter a valid number.") from exc
    if not number.is_finite():
        raise ValueError("Enter a valid number.")
    return number


def _q(value: Decimal) -> Decimal:
    return value.quantize(TWO_DP, rounding=ROUND_HALF_UP)


def total_pct(rec: dict) -> Decimal:
    """Total GST rate is 2 x the central tax rate shown in the notification."""
    return Decimal(rec["central_pct"]) * 2


def pct_text(value: Decimal) -> str:
    return str(_q(value))


def outcome_label(rec: dict) -> str:
    return OUTCOME_TEXT.get(rec["outcome"], "UNKNOWN - verify manually")


def gst_split(central_pct: Decimal, supply: str) -> dict:
    """Intra-State: CGST and SGST each equal the central rate.
    Inter-State: IGST equals the total GST rate."""
    total = central_pct * 2
    if supply == "inter":
        return {"total_pct": total, "cgst_pct": Decimal(0), "sgst_pct": Decimal(0), "igst_pct": total}
    return {"total_pct": total, "cgst_pct": central_pct, "sgst_pct": central_pct, "igst_pct": Decimal(0)}


class Catalogue:
    """Loads the dataset and answers search and browse questions."""

    def __init__(self, path: Path = DATA_PATH):
        with open(path, newline="", encoding="utf-8") as fh:
            self.records = list(csv.DictReader(fh))
        docs = [normalise(f"{r['description']} {r['category']}") for r in self.records]
        self._vectoriser = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5))
        self._matrix = self._vectoriser.fit_transform(docs)

    def categories(self) -> list[str]:
        return sorted({r["category"] for r in self.records})

    def slabs(self) -> list[Decimal]:
        """Slab list comes from the dataset, never from a fixed list."""
        return sorted({total_pct(r) for r in self.records})

    def taxable_records(self) -> list[dict]:
        return [r for r in self.records if r["outcome"] == "taxable"]

    def filter(self, category=None, slab=None) -> list[dict]:
        out = []
        for r in self.records:
            if category and r["category"] != category:
                continue
            if slab is not None and total_pct(r) != slab:
                continue
            out.append(r)
        return out

    def search(self, query: str, kind: str = "all", limit: int = 10) -> dict:
        text = (query or "").strip()
        if not text:
            return {"mode": "none", "message": NOT_FOUND, "items": []}
        allowed = [kind == "all" or r["kind"] == kind for r in self.records]

        # HSN / SAC code search: partial, digits only
        if re.fullmatch(r"[0-9 .]+", text):
            digits = re.sub(r"\D", "", text)
            if not digits:
                return {"mode": "none", "message": NOT_FOUND, "items": []}
            items = [
                r for ok, r in zip(allowed, self.records)
                if ok and re.sub(r"\D", "", r["code"]).startswith(digits)
            ]
            if items:
                return {"mode": "code", "message": "", "items": items[:limit]}
            return {"mode": "none", "message": NOT_FOUND, "items": []}

        # Name search: fuzzy, always labelled as suggestions
        scores = cosine_similarity(self._vectoriser.transform([normalise(text)]), self._matrix)[0]
        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        items = []
        for i in ranked:
            if allowed[i] and scores[i] >= SIMILARITY_THRESHOLD:
                items.append({**self.records[i], "score": round(float(scores[i]), 3)})
                if len(items) == limit:
                    break
        if not items:
            return {"mode": "none", "message": NOT_FOUND, "items": []}
        return {"mode": "suggestion", "message": SUGGESTION_NOTE, "items": items}


def calculate(amount, rate_pct, supply: str, mode: str, cess_pct="0") -> dict:
    """Add GST to a base amount, or extract GST from an inclusive amount."""
    amount = _to_decimal(amount)
    rate = _to_decimal(rate_pct)
    cess_rate = _to_decimal(cess_pct)
    if amount <= 0:
        raise ValueError("Base amount must be greater than zero.")
    if not Decimal(0) <= rate <= Decimal(100):
        raise ValueError("GST rate must be between 0 and 100 per cent.")
    if not Decimal(0) <= cess_rate <= Decimal(100):
        raise ValueError("Cess must be between 0 and 100 per cent.")
    if supply not in ("intra", "inter"):
        raise ValueError("Supply type must be intra-State or inter-State.")

    if mode == "add":
        taxable = _q(amount)
        tax = _q(amount * rate / 100)
    elif mode == "extract":
        taxable = _q(amount * 100 / (100 + rate))
        tax = _q(amount - taxable)
    else:
        raise ValueError("Choose add or extract mode.")

    if supply == "intra":
        cgst = _q(tax / 2)
        sgst = tax - cgst          # remainder, so CGST + SGST always equals tax
        igst = Decimal("0.00")
    else:
        cgst = sgst = Decimal("0.00")
        igst = tax

    cess = _q(taxable * cess_rate / 100)
    total_tax = tax + cess
    return {
        "mode": mode,
        "supply": supply,
        "rate": rate,
        "taxable": taxable,
        "tax": tax,
        "cgst": cgst,
        "sgst": sgst,
        "igst": igst,
        "cess": cess,
        "total_tax": total_tax,
        "final": taxable + total_tax,
        "rounding_note": (
            "Each figure is rounded to 2 decimals (half up). CGST is rounded and SGST takes the "
            "remainder, so CGST + SGST always equals total GST. In extract mode, cess is added on top "
            "of the extracted taxable value, so the final figure can differ from the amount you entered. "
            "This is an estimate for the chosen rate."
        ),
    }
