
from __future__ import annotations

import os
import time
import uuid
from dataclasses import asdict

import pandas as pd
import numpy as np
import streamlit as st
import matplotlib.pyplot as plt

from auth import require_login
from calibration import engineering_temperature_calibration, percentile_calibration, incident_aware_calibration, manual_calibration, calibration_table
from fcct_core import FCCTConfig, solve_lambda_r
from telemetry_loader import generate_sample_telemetry, load_telemetry_csv, load_topology_csv, validate_topology
from prometheus_connector import PrometheusMetricMap, fetch_prometheus_telemetry, test_prometheus_connection
from topology import merge_topology, topology_summary
from risk_engine import prepare_scaled_telemetry, compute_risk_timeline, component_risk_snapshot
from validation import build_validation_table
from report_generator import generate_html_report
from alerting import generate_alerts, alerts_to_slack_payload, post_webhook
from recommendations import build_recommendations
from db import connect, save_run, list_runs, load_table


st.set_page_config(page_title="FCCT GPU Cascade Guard V3", page_icon="🧠", layout="wide")
require_login()

DB_PATH = os.getenv("FCCT_DB_PATH", "data/fcct_guard.db")
conn = connect(DB_PATH)

st.title("FCCT GPU Cascade Guard V3")
st.caption("Deployable shadow-monitoring system with persistence, auth, Prometheus/DCGM, recommendations, and Helm/Docker packaging.")

with st.sidebar:
    st.header("Data Source")
    data_mode = st.radio("Source", ["Sample data", "CSV upload", "Prometheus/DCGM"], index=0)

    scenario = st.selectbox("Sample scenario", ["hot_aisle_cascade", "normal_day", "inference_spike", "fan_underperformance"], disabled=(data_mode != "Sample data"))
    sample_steps = st.slider("Sample steps", 80, 480, 180, disabled=(data_mode != "Sample data"))
    sample_seed = st.number_input("Sample seed", value=11, step=1, disabled=(data_mode != "Sample data"))

    st.header("Prometheus/DCGM")
    prom_url = st.text_input("Prometheus URL", value=os.getenv("PROMETHEUS_URL", "http://localhost:9090"), disabled=(data_mode != "Prometheus/DCGM"))
    prom_minutes = st.slider("Minutes to fetch", 10, 240, 60, disabled=(data_mode != "Prometheus/DCGM"))
    prom_step = st.selectbox("Step", ["15s", "30s", "60s", "120s"], index=2, disabled=(data_mode != "Prometheus/DCGM"))
    auto_refresh = st.checkbox("Auto refresh Prometheus", value=False, disabled=(data_mode != "Prometheus/DCGM"))
    refresh_seconds = st.slider("Refresh seconds", 30, 300, 60, disabled=(data_mode != "Prometheus/DCGM" or not auto_refresh))

    st.header("FCCT Settings")
    coherence_radius = st.slider("Coherence radius r", 0, 4, 1)
    risk_trigger = st.slider("Risk trigger", 0.05, 0.95, 0.45)
    min_risky_scale = st.slider("Minimum risky scale", 1, 5, 2)

    st.header("Calibration")
    cal_mode = st.selectbox("Calibration mode", ["engineering_limits", "percentile", "incident_aware", "manual"])
    safe_temp = st.slider("Safe temp", 45.0, 75.0, 60.0)
    warning_temp = st.slider("Warning temp", 55.0, 85.0, 70.0)
    critical_temp = st.slider("Critical temp", 80.0, 110.0, 95.0)
    manual_thresholds_str = st.text_input("Manual thresholds", value="60,70,78,86,91", disabled=(cal_mode != "manual"))

    st.header("Baselines")
    early_threshold = st.slider("Early threshold", 55.0, 85.0, 70.0)
    late_threshold = st.slider("Late threshold", 70.0, 100.0, 82.0)

    st.header("Alerts")
    webhook_url = st.text_input("Webhook URL", value=os.getenv("FCCT_WEBHOOK_URL", ""))


# ---------------- Load telemetry ----------------
data_source_label = data_mode

try:
    if data_mode == "Sample data":
        telemetry, topology = generate_sample_telemetry(steps=int(sample_steps), seed=int(sample_seed), scenario=scenario)
        data_source_label = f"sample:{scenario}"

    elif data_mode == "CSV upload":
        telem_file = st.file_uploader("Upload telemetry CSV", type=["csv"])
        topo_file = st.file_uploader("Upload topology CSV", type=["csv"])
        if telem_file is None:
            st.info("Upload telemetry CSV or switch to sample/Prometheus mode.")
            st.stop()
        telemetry = load_telemetry_csv(telem_file)
        if topo_file is not None:
            topology = load_topology_csv(topo_file)
        else:
            nodes = sorted(telemetry["node_id"].astype(str).unique())
            topology = pd.DataFrame({
                "node_id": nodes,
                "rack_id": ["uploaded-rack"] * len(nodes),
                "row": [0] * len(nodes),
                "col": list(range(len(nodes))),
                "zone": ["uploaded-zone"] * len(nodes),
            })
            topology = validate_topology(topology)
        data_source_label = "uploaded_csv"

    else:
        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("Test Prometheus"):
                st.json(test_prometheus_connection(prom_url))
        with col_b:
            fetch_clicked = st.button("Fetch Prometheus telemetry", type="primary")

        if fetch_clicked or "prometheus_telemetry" not in st.session_state:
            telemetry = fetch_prometheus_telemetry(prom_url, PrometheusMetricMap(), minutes=int(prom_minutes), step=prom_step)
            st.session_state["prometheus_telemetry"] = telemetry
        else:
            telemetry = st.session_state["prometheus_telemetry"]

        nodes = sorted(telemetry["node_id"].astype(str).unique())
        topology = pd.DataFrame({
            "node_id": nodes,
            "rack_id": [f"rack-{i//4 + 1}" for i in range(len(nodes))],
            "row": [i // 4 for i in range(len(nodes))],
            "col": [i % 4 for i in range(len(nodes))],
            "zone": ["prom-zone-A" if (i % 4) < 2 else "prom-zone-B" for i in range(len(nodes))],
        })
        topology = validate_topology(topology)
        data_source_label = f"prometheus:{prom_url}"

except Exception as e:
    st.error(f"Data loading failed: {e}")
    st.exception(e)
    st.stop()

merged_telemetry = merge_topology(telemetry, topology)
config = FCCTConfig(coherence_radius=int(coherence_radius), growth_height=1, max_scale=5, risk_trigger=float(risk_trigger), min_risky_scale=int(min_risky_scale))

# ---------------- Calibration ----------------
try:
    if cal_mode == "engineering_limits":
        cal = engineering_temperature_calibration(safe_temp, warning_temp, critical_temp)
    elif cal_mode == "percentile":
        cal = percentile_calibration(merged_telemetry, metric="temp_c", critical_cap=critical_temp)
    elif cal_mode == "incident_aware":
        cal = incident_aware_calibration(merged_telemetry, metric="temp_c", incident_col="throttle_flag")
    else:
        parts = [float(x.strip()) for x in manual_thresholds_str.split(",")]
        if len(parts) != 5:
            raise ValueError("Manual calibration requires exactly five comma-separated thresholds.")
        cal = manual_calibration(tuple(parts), metric="temp_c")
except Exception as e:
    st.error(f"Calibration failed: {e}")
    st.stop()

# ---------------- Risk computation ----------------
try:
    scaled = prepare_scaled_telemetry(merged_telemetry, cal, config)
    risk_timeline, edges = compute_risk_timeline(scaled, topology, config)
    validation_timeline, validation_summary = build_validation_table(risk_timeline, merged_telemetry, config.risk_trigger, early_threshold, late_threshold)
    alerts = generate_alerts(risk_timeline, config.risk_trigger)

    timestamps = list(risk_timeline["timestamp"])
    default_idx = int(risk_timeline["risk_score"].idxmax()) if len(risk_timeline) else 0
    default_idx = max(0, min(default_idx, len(timestamps) - 1))
    max_ts = timestamps[default_idx] if timestamps else ""
    snapshot_for_recs = component_risk_snapshot(scaled, max_ts, topology, config) if max_ts else pd.DataFrame()
    recommendations = build_recommendations(snapshot_for_recs, float(risk_timeline["risk_score"].max() if len(risk_timeline) else 0), config.min_risky_scale)
except Exception as e:
    st.error(f"Risk computation failed: {e}")
    st.exception(e)
    st.stop()

lam = solve_lambda_r(config.coherence_radius, config.growth_height)
summary = {
    "components": int(scaled["component_id"].nunique()),
    "timestamps": int(scaled["timestamp"].nunique()),
    "edges": int(len(edges)),
    "peak_risk": float(risk_timeline["risk_score"].max()),
    "peak_scale": int(risk_timeline["max_scale"].max()),
    "alert_frames": int((risk_timeline["risk_score"] >= config.risk_trigger).sum()),
}

# Auto refresh only after work is complete.
if data_mode == "Prometheus/DCGM" and auto_refresh:
    st.info(f"Auto refresh enabled. Refreshing every {refresh_seconds} seconds.")
    time.sleep(int(refresh_seconds))
    st.rerun()

# ---------------- Header metrics ----------------
cols = st.columns(7)
cols[0].metric("Source", data_source_label[:18])
cols[1].metric("Components", summary["components"])
cols[2].metric("Timestamps", summary["timestamps"])
cols[3].metric("Edges", summary["edges"])
cols[4].metric("λᵣ", f"{lam:.4f}")
cols[5].metric("Peak risk", f"{summary['peak_risk']:.3f}")
cols[6].metric("Alerts", summary["alert_frames"])

tabs = st.tabs(["Operations", "Recommendations", "Calibration", "Risk Timeline", "Snapshot", "Alerts", "Validation", "History", "Report", "Raw"])

with tabs[0]:
    st.subheader("Operations Overview")
    st.write("V3 is deployable shadow monitoring. It recommends operator actions but does not automatically control nodes.")
    st.json(topology_summary(topology))
    fig, ax = plt.subplots()
    ax.plot(risk_timeline["timestamp"], risk_timeline["risk_score"], label="FCCT risk")
    ax.axhline(config.risk_trigger, linestyle="--", label="trigger")
    ax.tick_params(axis="x", labelrotation=90)
    ax.set_ylabel("Risk score")
    ax.legend()
    st.pyplot(fig)

with tabs[1]:
    st.subheader("Recommended Operator Actions")
    st.dataframe(recommendations, use_container_width=True)

with tabs[2]:
    st.subheader("S0-S5 Calibration")
    st.write(cal.explanation)
    st.dataframe(calibration_table(cal), use_container_width=True)
    fig, ax = plt.subplots()
    ax.hist(pd.to_numeric(merged_telemetry["temp_c"], errors="coerce").dropna(), bins=40)
    for th in cal.thresholds:
        ax.axvline(th, linestyle="--")
    ax.set_xlabel("Temperature °C")
    st.pyplot(fig)

with tabs[3]:
    st.subheader("Risk Timeline")
    st.dataframe(risk_timeline, use_container_width=True)
    fig, ax = plt.subplots()
    ax.plot(risk_timeline["timestamp"], risk_timeline["risk_score"], label="risk")
    ax.plot(risk_timeline["timestamp"], risk_timeline["coherent_pairs"], label="coherent pairs")
    ax.plot(risk_timeline["timestamp"], risk_timeline["max_scale"], label="max scale")
    ax.tick_params(axis="x", labelrotation=90)
    ax.legend()
    st.pyplot(fig)
    st.download_button("Download risk CSV", risk_timeline.to_csv(index=False).encode("utf-8"), "fcct_v3_risk_timeline.csv", "text/csv")

with tabs[4]:
    st.subheader("Risk Snapshot")
    selected_ts = st.selectbox("Timestamp", timestamps, index=default_idx)
    snapshot = component_risk_snapshot(scaled, selected_ts, topology, config)
    st.dataframe(snapshot, use_container_width=True)
    if {"row", "col"}.issubset(snapshot.columns):
        node_map = snapshot.groupby(["row", "col"], as_index=False).agg(max_scale=("scale", "max"), max_temp=("temp_c", "max"), risky=("is_risky_component", "max"))
        if not node_map.empty and node_map["row"].notna().all() and node_map["col"].notna().all():
            rows = int(node_map["row"].max()) + 1
            cols2 = int(node_map["col"].max()) + 1
            grid = np.zeros((rows, cols2))
            for _, row in node_map.iterrows():
                grid[int(row["row"]), int(row["col"])] = row["max_scale"]
            fig, ax = plt.subplots()
            im = ax.imshow(grid, vmin=0, vmax=5)
            fig.colorbar(im, ax=ax, label="S-scale")
            ax.set_title(f"Node max S-scale at {selected_ts}")
            st.pyplot(fig)

with tabs[5]:
    st.subheader("Alerts")
    st.dataframe(alerts, use_container_width=True)
    payload = alerts_to_slack_payload(alerts)
    st.json(payload)
    if webhook_url and st.button("Send webhook"):
        st.json(post_webhook(webhook_url, payload))
    st.download_button("Download alerts JSON", pd.Series([payload]).to_json(indent=2).encode("utf-8"), "fcct_v3_alerts.json", "application/json")

with tabs[6]:
    st.subheader("Validation")
    st.dataframe(validation_summary, use_container_width=True)
    fig, ax = plt.subplots()
    ax.plot(validation_timeline["timestamp"], validation_timeline["fcct_alert"], label="FCCT")
    ax.plot(validation_timeline["timestamp"], validation_timeline["early_threshold_alert"], label="Early threshold")
    ax.plot(validation_timeline["timestamp"], validation_timeline["late_threshold_alert"], label="Late threshold")
    ax.plot(validation_timeline["timestamp"], validation_timeline["event"], label="Throttle event")
    ax.tick_params(axis="x", labelrotation=90)
    ax.legend()
    st.pyplot(fig)

with tabs[7]:
    st.subheader("Persistent History")
    run_id = st.text_input("Run ID", value=f"run-{uuid.uuid4().hex[:8]}")
    if st.button("Save current run to SQLite"):
        save_run(
            conn,
            run_id=run_id,
            source=data_source_label,
            config=asdict(config),
            calibration={"method": cal.method, "metric_name": cal.metric_name, "thresholds": cal.thresholds, "explanation": cal.explanation},
            summary=summary,
            risk_timeline=risk_timeline,
            alerts=alerts,
            recommendations=recommendations,
        )
        st.success(f"Saved run {run_id}")
    st.dataframe(list_runs(conn), use_container_width=True)

with tabs[8]:
    st.subheader("Report Export")
    html = generate_html_report(risk_timeline, validation_summary, calibration_table(cal), cal, config, topology_summary(topology), recommendations, data_source_label)
    st.download_button("Download HTML report", html.encode("utf-8"), "fcct_gpu_cascade_guard_v3_report.html", "text/html")
    st.components.v1.html(html, height=700, scrolling=True)

with tabs[9]:
    st.subheader("Scaled Telemetry")
    st.dataframe(scaled.head(3000), use_container_width=True)
    st.subheader("Topology")
    st.dataframe(topology, use_container_width=True)
    st.subheader("Edges")
    st.dataframe(pd.DataFrame(edges, columns=["component_a", "component_b"]), use_container_width=True)
