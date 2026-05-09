
from __future__ import annotations

from typing import Dict, Any
import requests
import pandas as pd


def generate_alerts(risk_timeline: pd.DataFrame, risk_trigger: float, max_alerts: int = 50) -> pd.DataFrame:
    alerts = risk_timeline[risk_timeline["risk_score"] >= risk_trigger].copy()
    if alerts.empty:
        return pd.DataFrame(columns=["timestamp", "severity", "message", "risk_score", "risky_components"])

    def severity(score: float) -> str:
        if score >= 0.75:
            return "critical"
        if score >= 0.60:
            return "high"
        return "warning"

    alerts["severity"] = alerts["risk_score"].apply(severity)
    alerts["message"] = alerts.apply(
        lambda r: (
            f"FCCT {r['severity'].upper()} cascade-risk alert at {r['timestamp']}: "
            f"risk={r['risk_score']:.3f}, max_scale=S{int(r['max_scale'])}, coherent_pairs={int(r['coherent_pairs'])}. "
            f"Risky components: {r.get('risky_components', '')}"
        ),
        axis=1,
    )
    cols = ["timestamp", "severity", "message", "risk_score", "max_scale", "coherent_pairs", "risky_components"]
    return alerts[cols].head(max_alerts).reset_index(drop=True)


def alerts_to_slack_payload(alerts: pd.DataFrame) -> Dict[str, Any]:
    if alerts.empty:
        text = "FCCT GPU Cascade Guard: no active cascade-risk alerts."
    else:
        lines = ["FCCT GPU Cascade Guard alerts:"]
        for _, row in alerts.iterrows():
            lines.append(f"- {row['message']}")
        text = "\n".join(lines)
    return {"text": text}


def post_webhook(webhook_url: str, payload: Dict[str, Any], timeout: int = 10) -> Dict[str, Any]:
    try:
        resp = requests.post(webhook_url, json=payload, timeout=timeout)
        return {"ok": resp.status_code < 400, "status_code": resp.status_code, "text": resp.text[:500]}
    except Exception as e:
        return {"ok": False, "error": str(e)}
