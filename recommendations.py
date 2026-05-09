
"""
Recommendation engine for FCCT GPU Cascade Guard V3.

V3 remains a shadow-mode product. These recommendations are operator actions,
not automatic control commands.
"""

from __future__ import annotations

from typing import List, Dict, Any
import pandas as pd


def _severity(score: float) -> str:
    if score >= 0.78:
        return "critical"
    if score >= 0.62:
        return "high"
    if score >= 0.45:
        return "warning"
    return "watch"


def build_recommendations(snapshot: pd.DataFrame, risk_score: float, min_scale: int = 2) -> pd.DataFrame:
    if snapshot.empty:
        return pd.DataFrame(columns=["priority", "scope", "target", "reason", "recommendation"])

    risky = snapshot[(snapshot["scale"] >= min_scale) | (snapshot.get("is_risky_component", False) == True)].copy()
    if risky.empty:
        return pd.DataFrame([{
            "priority": "low",
            "scope": "fleet",
            "target": "all",
            "reason": "No coherent high-scale cluster detected.",
            "recommendation": "Continue monitoring in shadow mode.",
        }])

    rows: List[Dict[str, Any]] = []
    severity = _severity(float(risk_score))

    # Rack/zone recommendations.
    for rack, group in risky.groupby("rack_id", dropna=False):
        max_temp = float(pd.to_numeric(group["temp_c"], errors="coerce").max())
        max_scale = int(group["scale"].max())
        count = int(group["component_id"].nunique())
        rows.append({
            "priority": severity,
            "scope": "rack",
            "target": str(rack),
            "reason": f"{count} risky GPU components, max scale S{max_scale}, max temp {max_temp:.1f}°C.",
            "recommendation": "Avoid scheduling new high-power jobs here; inspect airflow/cooling path; consider shifting low-priority jobs away.",
        })

    # Node-level recommendations.
    for node, group in risky.groupby("node_id", dropna=False):
        max_temp = float(pd.to_numeric(group["temp_c"], errors="coerce").max())
        max_util = float(pd.to_numeric(group.get("gpu_util", pd.Series([0])), errors="coerce").max())
        max_scale = int(group["scale"].max())
        rec = "Pause new job placement on this node and monitor."
        if max_temp >= 90 or max_scale >= 5:
            rec = "Cordon/avoid this node in scheduler; migrate non-critical workloads if safe; check fans/power/cooling."
        elif max_util >= 90 and max_temp >= 80:
            rec = "Reduce incoming workload pressure or rebalance inference traffic away from this node."
        rows.append({
            "priority": severity,
            "scope": "node",
            "target": str(node),
            "reason": f"Node has S{max_scale} risk, max temp {max_temp:.1f}°C, max util {max_util:.1f}%.",
            "recommendation": rec,
        })

    # Component-level hotlist.
    top = risky.sort_values(["scale", "temp_c"], ascending=False).head(10)
    for _, row in top.iterrows():
        rows.append({
            "priority": severity,
            "scope": "gpu",
            "target": str(row["component_id"]),
            "reason": f"GPU scale S{int(row['scale'])}, temp {float(row['temp_c']):.1f}°C.",
            "recommendation": "Inspect this GPU/job; avoid adding work; confirm thermal throttling and fan response.",
        })

    return pd.DataFrame(rows)
