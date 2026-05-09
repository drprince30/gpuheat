
from __future__ import annotations

from typing import Tuple, List
import pandas as pd
from fcct_core import FCCTConfig, ScaleCalibration, assign_scale, build_edges_from_topology, ensure_component_id, risk_for_frame


def prepare_scaled_telemetry(telemetry: pd.DataFrame, calibration: ScaleCalibration, config: FCCTConfig) -> pd.DataFrame:
    out = telemetry.copy()
    metric = calibration.metric_name
    if metric not in out.columns:
        raise ValueError(f"Telemetry missing calibration metric: {metric}")
    out["scale"] = assign_scale(out[metric], calibration, config.max_scale)
    out = ensure_component_id(out)
    return out


def compute_risk_timeline(scaled_telemetry: pd.DataFrame, topology: pd.DataFrame, config: FCCTConfig) -> Tuple[pd.DataFrame, List[Tuple[str, str]]]:
    components = scaled_telemetry[["node_id", "gpu_id", "component_id"]].drop_duplicates()
    edges = build_edges_from_topology(topology, components)

    rows = []
    for ts, frame in scaled_telemetry.groupby("timestamp", sort=True):
        risk = risk_for_frame(frame, edges, config)
        row = {
            "timestamp": ts,
            "risk_score": risk["risk_score"],
            "status": risk["status"],
            "current_energy_norm": risk["current_energy_norm"],
            "projected_energy_norm": risk["risk_score"],
            "coherent_pairs": risk["coherent_pairs"],
            "risky_pairs": risk["risky_pairs"],
            "max_scale": risk["max_scale"],
            "mean_scale": risk["mean_scale"],
            "critical_components": risk["critical_components"],
            "risky_component_count": len(risk["risky_components"]),
            "risky_components": ", ".join(risk["risky_components"][:30]),
        }
        for metric in ["temp_c", "power_w", "gpu_util", "fan_pct", "throttle_flag"]:
            if metric in frame.columns:
                vals = pd.to_numeric(frame[metric], errors="coerce")
                row[f"max_{metric}"] = float(vals.max())
                row[f"mean_{metric}"] = float(vals.mean())
        if "throttle_flag" in frame.columns:
            row["throttle_events"] = int(pd.to_numeric(frame["throttle_flag"], errors="coerce").fillna(0).sum())
        else:
            row["throttle_events"] = 0
        rows.append(row)

    return pd.DataFrame(rows), edges


def component_risk_snapshot(scaled_telemetry: pd.DataFrame, timestamp: str, topology: pd.DataFrame, config: FCCTConfig) -> pd.DataFrame:
    frame = scaled_telemetry[scaled_telemetry["timestamp"] == timestamp].copy()
    if frame.empty:
        return frame
    components = scaled_telemetry[["node_id", "gpu_id", "component_id"]].drop_duplicates()
    edges = build_edges_from_topology(topology, components)
    risk = risk_for_frame(frame, edges, config)
    risky_set = set(risk["risky_components"])
    frame["is_risky_component"] = frame["component_id"].isin(risky_set)
    frame["fleet_risk_score"] = risk["risk_score"]
    return frame.sort_values(["scale", "temp_c"], ascending=False)
