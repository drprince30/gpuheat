
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any, List
import time
import pandas as pd
import requests


@dataclass(frozen=True)
class PrometheusMetricMap:
    temp_c: str = "DCGM_FI_DEV_GPU_TEMP"
    power_w: str = "DCGM_FI_DEV_POWER_USAGE"
    gpu_util: str = "DCGM_FI_DEV_GPU_UTIL"
    mem_util: str = "DCGM_FI_DEV_MEM_COPY_UTIL"
    throttle: str = "DCGM_FI_DEV_CLOCK_THROTTLE_REASONS"


def _series_to_rows(metric_name: str, series: Dict[str, Any]) -> List[Dict[str, Any]]:
    labels = series.get("metric", {})
    values = series.get("values", [])
    node = labels.get("node") or labels.get("kubernetes_node") or labels.get("Hostname") or labels.get("host") or labels.get("instance") or "unknown-node"
    gpu = labels.get("gpu") or labels.get("GPU") or labels.get("device") or labels.get("UUID") or "0"

    rows = []
    for ts, value in values:
        try:
            v = float(value)
        except Exception:
            continue
        rows.append({
            "timestamp_unix": float(ts),
            "timestamp": time.strftime("t%Y%m%d%H%M%S", time.gmtime(float(ts))),
            "node_id": str(node).split(":")[0],
            "gpu_id": str(gpu),
            metric_name: v,
        })
    return rows


def prometheus_query_range(base_url: str, query: str, start: float, end: float, step: str = "60s", timeout: int = 20) -> List[Dict[str, Any]]:
    url = f"{base_url.rstrip('/')}/api/v1/query_range"
    resp = requests.get(url, params={"query": query, "start": start, "end": end, "step": step}, timeout=timeout)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("status") != "success":
        raise RuntimeError(f"Prometheus query failed: {payload}")
    return payload.get("data", {}).get("result", [])


def fetch_prometheus_telemetry(base_url: str, metric_map: PrometheusMetricMap, minutes: int = 60, step: str = "60s") -> pd.DataFrame:
    end = time.time()
    start = end - minutes * 60
    metric_queries = {
        "temp_c": metric_map.temp_c,
        "power_w": metric_map.power_w,
        "gpu_util": metric_map.gpu_util,
        "mem_util": metric_map.mem_util,
        "throttle_raw": metric_map.throttle,
    }

    frames = []
    for normalized_name, query in metric_queries.items():
        if not query:
            continue
        result = prometheus_query_range(base_url, query, start, end, step=step)
        rows = []
        for series in result:
            rows.extend(_series_to_rows(normalized_name, series))
        if rows:
            frames.append(pd.DataFrame(rows))

    if not frames:
        raise RuntimeError("No Prometheus metrics returned. Check URL, metric names, and time range.")

    keys = ["timestamp_unix", "timestamp", "node_id", "gpu_id"]
    merged = frames[0]
    for f in frames[1:]:
        merged = merged.merge(f, on=keys, how="outer")

    for c in ["temp_c", "power_w", "gpu_util", "mem_util", "throttle_raw"]:
        if c not in merged.columns:
            merged[c] = 0.0

    merged["throttle_flag"] = (pd.to_numeric(merged["throttle_raw"], errors="coerce").fillna(0) > 0).astype(int)
    if "fan_pct" not in merged.columns:
        merged["fan_pct"] = 0.0

    cols = ["timestamp", "node_id", "gpu_id", "temp_c", "power_w", "gpu_util", "mem_util", "fan_pct", "throttle_flag"]
    out = merged[cols].copy()
    out["timestamp"] = out["timestamp"].astype(str)
    return out.sort_values(["timestamp", "node_id", "gpu_id"]).reset_index(drop=True)


def test_prometheus_connection(base_url: str) -> Dict[str, Any]:
    try:
        resp = requests.get(f"{base_url.rstrip('/')}/api/v1/query", params={"query": "up"}, timeout=8)
        resp.raise_for_status()
        payload = resp.json()
        return {"ok": payload.get("status") == "success", "response": payload}
    except Exception as e:
        return {"ok": False, "error": str(e)}
