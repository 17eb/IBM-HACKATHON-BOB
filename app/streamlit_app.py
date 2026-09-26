"""COBOL Bridge demo: run a Java port live against frozen COBOL goldens and inspect exact parity."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import workflow  # noqa: E402
from core.records import INPUT_FIELDS, OUTPUT_FIELDS, TRAILER_FIELDS  # noqa: E402

CANDIDATES = {
    "Before: naive Java port (double), a deliberate baseline": "java-naive",
    "After: faithful Java port (BigDecimal)": "java",
}

st.set_page_config(page_title="COBOL Bridge", page_icon="🌉", layout="wide")

st.title("COBOL Bridge")
st.markdown(
    "**AI can translate COBOL, but it can't prove the translation is right.** COBOL Bridge is an MCP "
    "proof harness: an AI agent ports the program, and deterministic tools check every field of every "
    "record against the legacy output, down to the cent."
)
st.info(
    "**What runs live here:** the Java candidates are compiled and executed on this server when you "
    "click *Run*. The **COBOL goldens were captured locally with GnuCOBOL 3.2 and are committed** to the "
    "repository with their hashes. They are not produced on this server and are not IBM-runtime verified. "
    "All data is synthetic.",
    icon="ℹ️",
)

tab_run, tab_all, tab_program, tab_how = st.tabs(
    ["Run a parity check", "Before / after", "The COBOL program", "How it works"]
)


def show_error(result: dict) -> None:
    for err in result.get("errors", []):
        st.error(err.get("message", "unknown error"))
        if err.get("stderr"):
            st.code(err["stderr"], language="text")


with tab_run:
    datasets = workflow.list_datasets()
    if not datasets:
        st.error("No datasets found under data/inputs.")
        st.stop()
    col1, col2 = st.columns(2)
    dataset_id = col1.selectbox("Dataset", datasets, index=datasets.index("ds02_edges") if "ds02_edges" in datasets else 0)
    candidate_label = col2.radio("Candidate", list(CANDIDATES), horizontal=False)
    candidate = CANDIDATES[candidate_label]

    if st.button("▶ Run Java and compare with the COBOL golden", type="primary"):
        with st.spinner("Compiling and running Java, then comparing every field…"):
            st.session_state["report"] = workflow.compare_parity(dataset_id, candidate)

    report = st.session_state.get("report")
    if report:
        if report.get("status") == "error":
            show_error(report)
        else:
            if report["status"] == "pass":
                st.success(f"PASS: every record, field and the trailer match the COBOL golden exactly "
                           f"(`{report['dataset_id']}`, candidate `{report['candidate']}`).")
            else:
                st.error(f"FAIL: {report['mismatch_count']} field mismatches in "
                         f"{report['records_mismatched']} record(s); trailer "
                         f"{'matches' if report['trailer_match'] else 'does NOT match'} "
                         f"(`{report['dataset_id']}`, candidate `{report['candidate']}`).")
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Records", report["records_expected"])
            m2.metric("Exact matches", report["records_matched"])
            m3.metric("Field mismatches", report["mismatch_count"])
            m4.metric("Trailer", "match" if report["trailer_match"] else "MISMATCH")
            if report["mismatches"]:
                st.subheader("Mismatches")
                st.caption("Rule IDs: R1 interest rounding · R2 late fee (truncated, min 5.00) · "
                           "R3 fee doubling over 60 days · R4 validation · R5 trailer totals")
                st.dataframe([{**m, "record_no": str(m["record_no"])} for m in report["mismatches"]],
                             width="stretch", hide_index=True)
                st.bar_chart(report["mismatches_by_rule"], horizontal=True)
            with st.expander("Report provenance"):
                st.json({k: report[k] for k in ("run_id", "golden_path", "golden_origin", "golden_sha256",
                                                "candidate_sha256", "input_sha256", "created_at")})
            st.download_button("Download JSON report", json.dumps(report, indent=2),
                               file_name=f"{report['run_id']}.json", mime="application/json")

with tab_all:
    st.markdown("Run **both** Java candidates on **every** dataset. This is the before/after comparison: "
                "a quick port written without studying COBOL arithmetic, against the faithful port.")
    if st.button("Run all datasets for both candidates"):
        rows = []
        with st.spinner("Running 2 candidates × all datasets…"):
            for label, cand in CANDIDATES.items():
                for ds in workflow.list_datasets():
                    r = workflow.compare_parity(ds, cand)
                    if r.get("status") == "error":
                        rows.append({"candidate": cand, "dataset": ds, "status": "ERROR", "records": 0,
                                     "records wrong": 0, "field mismatches": 0, "trailer": "-", "by rule": "-"})
                        continue
                    rows.append({
                        "candidate": cand, "dataset": ds, "status": r["status"].upper(),
                        "records": r["records_expected"], "records wrong": r["records_mismatched"],
                        "field mismatches": r["mismatch_count"],
                        "trailer": "match" if r["trailer_match"] else "MISMATCH",
                        "by rule": ", ".join(f"{k}:{v}" for k, v in sorted(r["mismatches_by_rule"].items())) or "-",
                    })
        st.dataframe(rows, width="stretch", hide_index=True)

with tab_program:
    left, right = st.columns([3, 2])
    with left:
        st.subheader("legacy/LOANCALC.cbl")
        st.code((ROOT / "legacy" / "LOANCALC.cbl").read_text(), language="cobol", line_numbers=True)
    with right:
        st.subheader("Record layouts")
        for title, fields in (("Input (28 bytes)", INPUT_FIELDS), ("Output detail (37 bytes)", OUTPUT_FIELDS),
                              ("Trailer (28 bytes)", TRAILER_FIELDS)):
            st.markdown(f"**{title}**")
            st.dataframe([{"field": f.name, "cols": f"{f.start}–{f.start + f.width - 1}", "width": f.width,
                           "implied decimals": str(f.scale) if f.scale is not None else "-",
                           "rule": f.rule or "-"} for f in fields], hide_index=True, width="stretch")
        st.subheader("Why ports drift")
        st.markdown(
            "- **R1:** `COMPUTE … ROUNDED` rounds half **up**. Java's `Math.rint` and `HALF_EVEN` round a "
            "half cent to the even digit, so 1410.945 becomes 1410.94 instead of 1410.95.\n"
            "- **R2:** the fee `COMPUTE` has **no** `ROUNDED`, so COBOL **truncates**: 15.8075 becomes 15.80, "
            "not 15.81.\n"
            "- **R5:** a single wrong cent in any record breaks the batch trailer total."
        )

with tab_how:
    st.markdown(
        """
**Workflow:** explain → characterize → port → verify → report

1. `inspect_cobol` reads the source: paragraphs, PIC clauses, `COMPUTE` statements, and questions for the port.
2. `capture_golden` compiles and runs the COBOL on synthetic inputs, then freezes the output together with a manifest (hashes, compiler, profile).
3. The AI agent writes the Java port.
4. `compare_parity` runs Java on the same bytes and compares every field and the trailer exactly. Each mismatch is tied to a business rule.
5. The agent fixes the **Java**, never the golden, and loops until every dataset passes.

These tools are exposed through a **Model Context Protocol server** (`python -m mcp_server.server`), so any MCP-capable agent, including IBM Bob, can drive the loop. This page calls the same `core/` library as the MCP server.
"""
    )
