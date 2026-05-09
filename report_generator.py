
from __future__ import annotations

from typing import Dict, Any
from html import escape
import pandas as pd
from fcct_core import ScaleCalibration, FCCTConfig


def df_to_html_table(df: pd.DataFrame, max_rows: int = 20) -> str:
    if df is None or df.empty:
        return "<p>No data.</p>"
    return df.head(max_rows).to_html(index=False, escape=True)


def generate_html_report(
    risk_timeline: pd.DataFrame,
    validation_summary: pd.DataFrame,
    calibration_table: pd.DataFrame,
    calibration: ScaleCalibration,
    config: FCCTConfig,
    topology_summary: Dict[str, Any],
    recommendations: pd.DataFrame,
    data_source: str = "unknown",
) -> str:
    peak_risk = float(risk_timeline["risk_score"].max()) if not risk_timeline.empty else 0.0
    peak_scale = int(risk_timeline["max_scale"].max()) if not risk_timeline.empty else 0
    event_frames = int((risk_timeline.get("throttle_events", pd.Series(dtype=int)) > 0).sum()) if not risk_timeline.empty else 0
    alert_frames = int((risk_timeline["risk_score"] >= config.risk_trigger).sum()) if not risk_timeline.empty else 0

    return f"""
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>FCCT GPU Cascade Guard V3 Report</title>
<style>
body {{ font-family: Arial, sans-serif; line-height: 1.5; margin: 32px; }}
h1, h2 {{ color: #222; }}
.card {{ border: 1px solid #ddd; padding: 16px; border-radius: 8px; margin: 12px 0; }}
table {{ border-collapse: collapse; width: 100%; font-size: 14px; }}
th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
th {{ background: #f2f2f2; }}
</style>
</head>
<body>
<h1>FCCT GPU Cascade Guard V3 - Pilot / Operations Report</h1>

<div class="card">
<h2>Executive Summary</h2>
<p><b>Data source:</b> {escape(data_source)}</p>
<p><b>Peak FCCT risk score:</b> {peak_risk:.3f}</p>
<p><b>Peak symbolic scale:</b> S{peak_scale}</p>
<p><b>FCCT alert frames:</b> {alert_frames}</p>
<p><b>Observed throttle/incident frames:</b> {event_frames}</p>
<p><b>Topology:</b> {escape(str(topology_summary))}</p>
</div>

<div class="card">
<h2>Recommended Operator Actions</h2>
{df_to_html_table(recommendations, max_rows=30)}
</div>

<div class="card">
<h2>Calibration</h2>
<p><b>Method:</b> {escape(calibration.method)}</p>
<p><b>Metric:</b> {escape(calibration.metric_name)}</p>
<p><b>Thresholds:</b> {escape(str(tuple(round(x, 2) for x in calibration.thresholds)))}</p>
<p>{escape(calibration.explanation)}</p>
{df_to_html_table(calibration_table, max_rows=10)}
</div>

<div class="card">
<h2>FCCT Configuration</h2>
<p><b>Coherence radius r:</b> {config.coherence_radius}</p>
<p><b>Growth height h:</b> {config.growth_height}</p>
<p><b>Risk trigger:</b> {config.risk_trigger}</p>
<p><b>Minimum risky scale:</b> S{config.min_risky_scale}</p>
</div>

<div class="card">
<h2>Validation Summary</h2>
{df_to_html_table(validation_summary, max_rows=20)}
</div>

<div class="card">
<h2>Top Risk Frames</h2>
{df_to_html_table(risk_timeline.sort_values("risk_score", ascending=False), max_rows=20)}
</div>

<div class="card">
<h2>Honest Limitations</h2>
<ul>
<li>V3 supports deployable shadow monitoring and recommendations, not automatic control.</li>
<li>Recommendations should be reviewed by operators before action.</li>
<li>S0-S5 calibration must be validated on customer telemetry and incidents.</li>
<li>Prometheus/DCGM labels vary by cluster and may require metric-map tuning.</li>
<li>Production automation requires separate safety testing and change-management approval.</li>
</ul>
</div>
</body>
</html>
"""
