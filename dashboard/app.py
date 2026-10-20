"""Streamlit dashboard. Run with:  streamlit run dashboard/app.py
Uses the same AnalysisService/SQLite database as the REST API (set LOGINTEL_DB to share it)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import streamlit as st

from logintel.detectors import DETECTORS
from logintel.exceptions import LogIntelError
from logintel.service import AnalysisService

st.set_page_config(page_title="Log Intelligence", layout="wide")


@st.cache_resource
def get_service() -> AnalysisService:
    return AnalysisService()


svc = get_service()
page = st.sidebar.radio("Page", ["Upload & analyse", "Anomaly review", "Incidents", "History", "Reports"])
st.sidebar.caption("Hints are heuristic; verify before acting.")


def pick_run() -> dict | None:
    runs = [r for r in svc.storage.list_runs() if r["status"] == "completed"]
    if not runs:
        st.info("No completed runs yet. Upload a batch and analyse it first.")
        return None
    labels = {f"run {r['id']} | batch {r['batch_id']} | {r['detector']} | {r['n_anomalies']} anomalies": r for r in runs}
    return labels[st.selectbox("Analysis run", list(labels))]


if page == "Upload & analyse":
    st.header("Upload & analyse")
    up = st.file_uploader("CSV or plain-text log file", type=["csv", "log", "txt"])
    name = st.text_input("Batch name (optional)")
    if up is not None and st.button("Ingest"):
        try:
            b = svc.ingest_bytes(up.getvalue(), up.name, name or None)
            st.success(f"Stored batch {b['id']} with {b['n_rows']} records (labels: {b['has_labels']}).")
            for w in b["warnings"]:
                st.warning(w)
        except LogIntelError as exc:
            st.error(str(exc))
    batches = svc.storage.list_batches()
    if batches:
        st.dataframe(pd.DataFrame(batches)[["id", "name", "source_format", "n_rows", "has_labels", "t_min", "t_max"]])
        bid = st.selectbox("Batch to analyse", [b["id"] for b in batches])
        det = st.selectbox("Detector", list(DETECTORS))
        c1, c2, c3 = st.columns(3)
        contamination = c1.slider("Expected anomaly rate", 0.01, 0.30, 0.05, 0.01)
        train_fraction = c2.slider("Chronological train fraction", 0.1, 0.9, 0.6, 0.05)
        ref = c3.selectbox("Reference (training) batch", [None] + [b["id"] for b in batches if b["id"] != bid])
        if st.button("Run analysis"):
            try:
                with st.spinner("Analysing..."):
                    run = svc.analyze(bid, det, contamination, ref, train_fraction)
                st.success(f"Run {run['id']}: {run['n_anomalies']} anomalies flagged.")
                if run["metrics"]:
                    st.json(run["metrics"])
                else:
                    st.info("No labels on held-out rows, so no metrics were computed.")
            except LogIntelError as exc:
                st.error(str(exc))
        if st.button("Compare all detectors on this batch"):
            with st.spinner("Running all detectors..."):
                res = svc.compare_detectors(bid, contamination=contamination, train_fraction=train_fraction)
            st.dataframe(pd.DataFrame([{"detector": r["detector"], "status": r.get("status"), "anomalies": r.get("n_anomalies"),
                                        "error": r.get("error"), **{k: (r.get("metrics") or {}).get(k)
                                                                    for k in ("precision", "recall", "f1", "roc_auc", "pr_auc")}}
                                       for r in res]))

elif page == "Anomaly review":
    st.header("Anomaly review")
    run = pick_run()
    if run:
        items = svc.storage.get_findings(run["id"], limit=1000)
        if items:
            df = pd.DataFrame(items)
            c1, c2, c3 = st.columns(3)
            svcs = c1.multiselect("Service", sorted(df["service"].unique()))
            lvls = c2.multiselect("Level", sorted(df["level"].unique()))
            min_s = c3.slider("Min score", 0.0, 1.0, 0.0, 0.05)
            view = df[(df["score"] >= min_s) & (df["service"].isin(svcs) if svcs else True) & (df["level"].isin(lvls) if lvls else True)]
            st.caption(f"{len(view)} of {len(df)} shown (max 1000 loaded)")
            st.dataframe(view[["ts", "level", "service", "score", "message"]], use_container_width=True)
            if len(view):
                idx = st.number_input("Inspect row # (in the table above)", 0, len(view) - 1, 0)
                st.json(view.iloc[int(idx)]["evidence"])
        else:
            st.info("No anomalies flagged in this run.")

elif page == "Incidents":
    st.header("Incident groups and root-cause hints")
    run = pick_run()
    if run:
        for inc in svc.storage.get_incidents(run["id"]):
            prefix = "Origin candidate" if inc["rank_in_group"] == 1 else "Related"
            st.markdown(f"**Group {inc['group_id']} - {prefix}: `{inc['service']}`** ({inc['category']}, {inc['n_events']} events)")
            st.caption(f"{inc['start']} -> {inc['end']}")
            st.write(inc["hypothesis"])

elif page == "History":
    st.header("Comparison with historical runs")
    run = pick_run()
    if run:
        h = svc.history_comparison(run["id"])
        st.write(f"Prior runs of `{h['detector']}`: {h['n_prior_runs']}")
        st.metric("Anomaly rate", f"{h['current_anomaly_rate']:.2%}",
                  None if h["rate_delta"] is None else f"{h['rate_delta']:+.2%} vs prior mean")
        st.subheader("New anomalous patterns"); st.dataframe(pd.DataFrame(h["new_patterns"]))
        st.subheader("Recurring patterns"); st.dataframe(pd.DataFrame(h["recurring_patterns"]))
        st.subheader("Recurring incident signatures"); st.dataframe(pd.DataFrame(h["recurring_incident_signatures"]))

else:
    st.header("Download reports")
    run = pick_run()
    if run:
        for fmt, mime in (("md", "text/markdown"), ("csv", "text/csv"), ("json", "application/json")):
            content, _ = svc.report(run["id"], fmt)
            st.download_button(f"Download {fmt.upper()}", content, f"run_{run['id']}.{fmt}", mime)
