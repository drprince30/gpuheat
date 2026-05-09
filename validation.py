
from __future__ import annotations

from typing import Dict, Any, Optional, Tuple
import pandas as pd


def make_threshold_baseline(telemetry: pd.DataFrame, threshold: float, metric: str = "temp_c", label: str = "threshold") -> pd.DataFrame:
    rows = []
    for ts, frame in telemetry.groupby("timestamp", sort=True):
        vals = pd.to_numeric(frame[metric], errors="coerce")
        alerts = vals >= threshold
        rows.append({"timestamp": ts, f"{label}_alert": int(alerts.any()), f"{label}_alert_components": int(alerts.sum()), f"{label}_max_{metric}": float(vals.max())})
    return pd.DataFrame(rows)


def attach_event_labels(timeline: pd.DataFrame, event_col: str = "throttle_events") -> pd.DataFrame:
    out = timeline.copy()
    out["event"] = (pd.to_numeric(out.get(event_col, 0), errors="coerce").fillna(0) > 0).astype(int)
    return out


def first_alert_lead_time(timeline: pd.DataFrame, alert_col: str, event_col: str = "event") -> Optional[int]:
    df = timeline.reset_index(drop=True)
    event_idxs = df.index[df[event_col] > 0].tolist()
    if not event_idxs:
        return None
    first_event = event_idxs[0]
    alert_idxs = df.index[(df[alert_col] > 0) & (df.index < first_event)].tolist()
    if not alert_idxs:
        return None
    return int(first_event - alert_idxs[0])


def alert_metrics(timeline: pd.DataFrame, alert_col: str, event_col: str = "event") -> Dict[str, Any]:
    df = timeline.copy()
    y_true = (df[event_col] > 0).astype(int)
    y_pred = (df[alert_col] > 0).astype(int)
    tp = int(((y_true == 1) & (y_pred == 1)).sum())
    fp = int(((y_true == 0) & (y_pred == 1)).sum())
    fn = int(((y_true == 1) & (y_pred == 0)).sum())
    tn = int(((y_true == 0) & (y_pred == 0)).sum())
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    return {"alert_col": alert_col, "tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": precision, "recall": recall, "first_alert_lead_time_steps": first_alert_lead_time(df, alert_col, event_col), "alert_frames": int(y_pred.sum()), "event_frames": int(y_true.sum())}


def build_validation_table(risk_timeline: pd.DataFrame, telemetry: pd.DataFrame, fcct_trigger: float, early_threshold: float, late_threshold: float) -> Tuple[pd.DataFrame, pd.DataFrame]:
    timeline = attach_event_labels(risk_timeline)
    timeline["fcct_alert"] = (timeline["risk_score"] >= fcct_trigger).astype(int)
    early = make_threshold_baseline(telemetry, early_threshold, label="early_threshold")
    late = make_threshold_baseline(telemetry, late_threshold, label="late_threshold")
    merged = timeline.merge(early, on="timestamp", how="left").merge(late, on="timestamp", how="left")
    summary = pd.DataFrame([alert_metrics(merged, col, event_col="event") for col in ["fcct_alert", "early_threshold_alert", "late_threshold_alert"]])
    return merged, summary
