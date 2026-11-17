"""GST TAXORA - Streamlit entry point. Run with: streamlit run app.py"""
from decimal import Decimal, InvalidOperation

import streamlit as st

from core.engine import (
    DATASET_VERSION,
    DISCLAIMER,
    NOT_FOUND,
    Catalogue,
    calculate,
    gst_split,
    outcome_label,
    pct_text,
    total_pct,
)
from core.export import build_rows, to_csv, to_pdf, to_xlsx

st.set_page_config(page_title="GST TAXORA", page_icon="🧾", layout="wide")

KIND_MAP = {"All": "all", "Goods": "goods", "Services": "service"}
MAX_HISTORY = 10
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@st.cache_resource
def get_catalogue() -> Catalogue:
    return Catalogue()


cat = get_catalogue()

if "history" not in st.session_state:
    st.session_state.history = []


def remember(query: str) -> None:
    q = query.strip()
    others = [h for h in st.session_state.history if h.lower() != q.lower()]
    st.session_state.history = ([q] + others)[:MAX_HISTORY]


# ---------- Sidebar: supply type and privacy controls ----------
with st.sidebar:
    st.header("Settings")
    supply_choice = st.radio(
        "Supply type",
        ["Intra-State (CGST + SGST)", "Inter-State (IGST)"],
        help="Intra-State supply is split into CGST and SGST. Inter-State supply attracts IGST.",
    )
    supply = "intra" if supply_choice.startswith("Intra") else "inter"

    keep_history = st.toggle("Keep recent searches (this session only)", value=False)
    if not keep_history:
        st.session_state.history = []
    if st.button("Clear history"):
        st.session_state.history = []
        st.toast("Recent searches cleared.")
    st.caption(
        "Recent searches are held in this app session's memory only. They are not saved "
        "to disk, a database or your browser, and they end when the session ends."
    )
    st.caption(f"Dataset: {DATASET_VERSION}")

st.title("🧾 GST TAXORA (India)")
st.caption("Informational only. Always verify the official notification before invoicing or filing.")


def show_record(rec: dict) -> None:
    split = gst_split(Decimal(rec["central_pct"]), supply)
    total = total_pct(rec)
    with st.container(border=True):
        st.subheader(rec["description"])
        st.markdown(f"**{outcome_label(rec)}**")
        c1, c2, c3 = st.columns(3)
        c1.metric("HSN / SAC", rec["code"])
        c2.metric("Total GST rate", f"{pct_text(total)}%")
        c3.metric("Cess", "See note" if rec["cess_note"] else "None recorded")
        if rec["outcome"] == "taxable":
            if supply == "intra":
                st.write(f"CGST {pct_text(split['cgst_pct'])}% + SGST/UTGST {pct_text(split['sgst_pct'])}%")
            else:
                st.write(f"IGST {pct_text(split['igst_pct'])}%")
        if rec["cess_note"]:
            st.warning(rec["cess_note"])
        if rec["condition"]:
            st.info(f"Condition: {rec['condition']}. Confirm this condition before relying on the rate.")
        st.caption(
            f"Notification: {rec['notification']} | Schedule: {rec['schedule']} | "
            f"Serial: {rec['serial_no']} | Effective from: {rec['effective_from']} | "
            f"Status: {rec['verification_status']}"
        )
        st.markdown(f"[Official source (CBIC)]({rec['source_url']})")


tab_search, tab_browse, tab_calc, tab_privacy = st.tabs(
    ["Search", "Browse", "Calculator", "Privacy and sources"]
)

# ---------- Search ----------
with tab_search:
    query = st.text_input(
        "Goods or services name, HSN code or SAC code",
        placeholder="e.g. cement, wheat, rice pre packged, 2523, 9985",
        max_chars=100,
    )
    scope = st.radio("Search in", list(KIND_MAP), horizontal=True)
    if query.strip():
        if keep_history:
            remember(query)
        result = cat.search(query, KIND_MAP[scope])
        if not result["items"]:
            st.error(NOT_FOUND)
        else:
            if result["mode"] == "suggestion":
                st.info(result["message"])
            for rec in result["items"]:
                show_record(rec)
            rows = build_rows(result["items"], supply)
            d1, d2, d3 = st.columns(3)
            d1.download_button("Download CSV", to_csv(rows), "gst_results.csv", "text/csv")
            d2.download_button("Download XLSX", to_xlsx(rows), "gst_results.xlsx", XLSX_MIME)
            d3.download_button("Download PDF", to_pdf("GST TAXORA - search results", rows),
                               "gst_results.pdf", "application/pdf")
    if st.session_state.history:
        st.caption("Recent searches: " + "  |  ".join(st.session_state.history))

# ---------- Browse ----------
with tab_browse:
    category = st.selectbox("Category", ["All categories"] + cat.categories())
    slab_options = {"All slabs": None}
    for s in cat.slabs():
        slab_options[f"{pct_text(s)}%"] = s
    slab_label = st.selectbox("GST slab (taken from the dataset)", list(slab_options))
    matches = cat.filter(None if category == "All categories" else category, slab_options[slab_label])
    st.caption(f"{len(matches)} record(s) shown. Slab options come from the dataset, not a fixed list.")
    if not matches:
        st.error("No records match these filters.")
    for rec in matches:
        show_record(rec)

# ---------- Calculator ----------
with tab_calc:
    st.subheader("GST calculator")
    st.caption("An estimate for the rate you pick. It does not classify the item.")
    options = {"Enter a rate manually": None}
    for r in cat.taxable_records():
        options[f"{r['description']} ({pct_text(total_pct(r))}%)"] = r
    source = st.selectbox("Rate source", list(options))
    picked = options[source]
    if picked is None:
        rate_str = str(st.number_input("GST rate (%)", min_value=0.0, max_value=100.0, value=18.0, step=0.5))
    else:
        rate_str = str(total_pct(picked))
        st.caption(f"Rate taken from dataset record {picked['id']}. Check its condition on the Search tab.")

    amount_text = st.text_input("Base amount (Rs.)", value="1000", max_chars=15)
    mode_choice = st.radio("Calculation", ["Add GST to base amount", "Extract GST from inclusive amount"])
    cess_value = st.number_input("Cess (%) - optional, leave 0 if none applies",
                                 min_value=0.0, max_value=100.0, value=0.0, step=0.5)
    mode = "add" if mode_choice.startswith("Add") else "extract"

    try:
        amount = Decimal(amount_text.replace(",", "").strip())
    except InvalidOperation:
        st.error("Enter a valid amount, for example 1000 or 2500.50.")
    else:
        try:
            out = calculate(amount, rate_str, supply, mode, str(cess_value))
        except ValueError as exc:
            st.error(str(exc))
        else:
            m1, m2, m3 = st.columns(3)
            m1.metric("Taxable value (Rs.)", f"{out['taxable']:,}")
            m2.metric("Total tax (Rs.)", f"{out['total_tax']:,}")
            m3.metric("Final amount (Rs.)", f"{out['final']:,}")
            parts = [("CGST", out["cgst"]), ("SGST/UTGST", out["sgst"]),
                     ("IGST", out["igst"]), ("Cess", out["cess"])]
            st.table([{"Component": n, "Amount (Rs.)": f"{v:,}"} for n, v in parts])
            st.caption(out["rounding_note"])
            calc_rows = [{
                "Mode": mode_choice,
                "Supply": supply_choice,
                "Rate %": rate_str,
                "Taxable value": str(out["taxable"]),
                "CGST": str(out["cgst"]),
                "SGST/UTGST": str(out["sgst"]),
                "IGST": str(out["igst"]),
                "Cess": str(out["cess"]),
                "Total tax": str(out["total_tax"]),
                "Final amount": str(out["final"]),
                "Dataset version": DATASET_VERSION,
            }]
            e1, e2 = st.columns(2)
            e1.download_button("Download calculation CSV", to_csv(calc_rows),
                               "gst_calculation.csv", "text/csv")
            e2.download_button("Download calculation PDF",
                               to_pdf("GST TAXORA - calculation", calc_rows),
                               "gst_calculation.pdf", "application/pdf")

# ---------- Privacy and sources ----------
with tab_privacy:
    st.subheader("Privacy notice")
    st.markdown(
        "**Operator:** [Add the name and address of the person or company running this app]  \n"
        "**Privacy contact:** [Add an email address you check regularly]  \n"
        "**Security incident contact:** [Add the same or a separate monitored address]"
    )
    st.markdown("""
- **What we process.** Your search text, settings and calculator inputs. These are used only to return results for the current session.
- **What we do not collect.** No accounts, no phone numbers, no email addresses, no Aadhaar, PAN, bank or card details, no location, no photos and no contacts.
- **Recent searches.** Off by default. When on, they stay in the app session's memory and end with the session. Use Clear history to delete them at any time.
- **Analytics and advertising.** None in this version. No trackers, ad pixels or session replay.
- **Voice search.** Not included in this version.
- **Hosting.** The app runs on Streamlit Community Cloud. The hosting provider may keep technical request logs under its own privacy policy.
- **Your rights.** Under the Digital Personal Data Protection Act, 2023, you may have rights to access, correction, erasure, grievance redressal and nomination once the relevant provisions are in force. Raise a grievance first with the privacy contact above. If it is not resolved, you can complain to the Data Protection Board of India.
- **Timing.** The main DPDP obligations are scheduled to commence on 13 May 2027. Verify the current position before launch.
- **Status.** This app is designed to align with the DPDP framework. It is not a certification of compliance.
""")
    st.subheader("Data sources and change log")
    st.markdown("""
- Central Tax (Rate) Notification 09/2025, G.S.R. 641(E): goods rates, Schedules I to VII.
- Central Tax (Rate) Notification 10/2025, G.S.R. 660(E): goods exemption list.
- Central Tax (Rate) Notification 11/2017, G.S.R. 690(E): services rates, as amended by later notifications.
- Source portal: https://www.cbic.gov.in
""")
    st.caption(f"Change log: {DATASET_VERSION}. First seed: 13 goods and 6 services. Rows marked 'pending' or 'needs check' must be verified.")
    st.subheader("Disclaimer")
    st.info(DISCLAIMER)
