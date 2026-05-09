
from __future__ import annotations

from typing import Tuple, Optional
import numpy as np
import pandas as pd
from fcct_core import ScaleCalibration


def engineering_temperature_calibration(
    safe_temp: float = 60.0,
    warning_temp: float = 70.0,
    critical_temp: float = 95.0,
) -> ScaleCalibration:
    if not (safe_temp < warning_temp < critical_temp):
        raise ValueError("Require safe_temp < warning_temp < critical_temp")
    t0 = float(safe_temp)
    t1 = float(warning_temp)
    t2 = float(warning_temp + 0.35 * (critical_temp - warning_temp))
    t3 = float(warning_temp + 0.65 * (critical_temp - warning_temp))
    t4 = float(warning_temp + 0.85 * (critical_temp - warning_temp))
    return ScaleCalibration(
        thresholds=(t0, t1, t2, t3, t4),
        method="engineering_limits",
        metric_name="temp_c",
        explanation="Engineering-limit calibration with S2 beginning at the warning boundary and S5 near critical.",
    )


def percentile_calibration(
    telemetry: pd.DataFrame,
    metric: str = "temp_c",
    critical_cap: Optional[float] = None,
) -> ScaleCalibration:
    if metric not in telemetry.columns:
        raise ValueError(f"telemetry missing metric column: {metric}")
    vals = pd.to_numeric(telemetry[metric], errors="coerce").dropna().to_numpy()
    if vals.size < 50:
        raise ValueError("Need at least 50 numeric readings for percentile calibration.")
    p60, p75, p85, p92, p97 = np.percentile(vals, [60, 75, 85, 92, 97])
    thresholds = [float(p60), float(p75), float(p85), float(p92), float(p97)]
    if critical_cap is not None:
        thresholds[-1] = min(thresholds[-1], float(critical_cap))
    return ScaleCalibration(
        thresholds=tuple(sorted(thresholds)),  # type: ignore[arg-type]
        method="percentile",
        metric_name=metric,
        explanation="Percentile calibration learned from the fleet telemetry distribution.",
    )


def incident_aware_calibration(
    telemetry: pd.DataFrame,
    metric: str = "temp_c",
    incident_col: str = "throttle_flag",
) -> ScaleCalibration:
    if metric not in telemetry.columns:
        raise ValueError(f"telemetry missing metric column: {metric}")
    if incident_col not in telemetry.columns:
        raise ValueError(f"telemetry missing incident column: {incident_col}")

    values = pd.to_numeric(telemetry[metric], errors="coerce")
    flags = pd.to_numeric(telemetry[incident_col], errors="coerce").fillna(0).astype(int)
    normal = values[flags == 0].dropna()
    incident = values[flags > 0].dropna()

    if len(normal) < 50:
        raise ValueError("Need at least 50 normal readings for incident-aware calibration.")
    if len(incident) < 5:
        cal = percentile_calibration(telemetry, metric=metric)
        return ScaleCalibration(
            thresholds=cal.thresholds,
            method="incident_aware_fallback_percentile",
            metric_name=metric,
            explanation="Not enough incident labels; percentile calibration was used.",
        )

    p60, p75, p85 = np.percentile(normal, [60, 75, 85])
    inc25, inc50 = np.percentile(incident, [25, 50])
    thresholds = tuple(sorted([float(p60), float(p75), float(p85), float(inc25), float(inc50)]))
    return ScaleCalibration(
        thresholds=thresholds,  # type: ignore[arg-type]
        method="incident_aware",
        metric_name=metric,
        explanation="Incident-aware calibration anchored using historical throttle/incident values.",
    )


def manual_calibration(thresholds: Tuple[float, float, float, float, float], metric: str = "temp_c") -> ScaleCalibration:
    if len(thresholds) != 5:
        raise ValueError("manual calibration requires exactly five thresholds")
    return ScaleCalibration(
        thresholds=tuple(sorted(float(x) for x in thresholds)),  # type: ignore[arg-type]
        method="manual",
        metric_name=metric,
        explanation="Manual calibration provided by operator.",
    )


def calibration_table(cal: ScaleCalibration) -> pd.DataFrame:
    return pd.DataFrame([
        {"state": "S0", "condition": f"{cal.metric_name} < {cal.thresholds[0]:.2f}", "meaning": "normal / safe"},
        {"state": "S1", "condition": f"{cal.thresholds[0]:.2f} ≤ {cal.metric_name} < {cal.thresholds[1]:.2f}", "meaning": "mild stress"},
        {"state": "S2", "condition": f"{cal.thresholds[1]:.2f} ≤ {cal.metric_name} < {cal.thresholds[2]:.2f}", "meaning": "early warning"},
        {"state": "S3", "condition": f"{cal.thresholds[2]:.2f} ≤ {cal.metric_name} < {cal.thresholds[3]:.2f}", "meaning": "high stress"},
        {"state": "S4", "condition": f"{cal.thresholds[3]:.2f} ≤ {cal.metric_name} < {cal.thresholds[4]:.2f}", "meaning": "near critical"},
        {"state": "S5", "condition": f"{cal.metric_name} ≥ {cal.thresholds[4]:.2f}", "meaning": "critical / throttling risk"},
    ])
