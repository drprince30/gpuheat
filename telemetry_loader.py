
from __future__ import annotations

from pathlib import Path
from typing import Tuple
import numpy as np
import pandas as pd


REQUIRED_TELEMETRY_COLUMNS = ["timestamp", "node_id", "gpu_id", "temp_c"]


def validate_telemetry(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    missing = [c for c in REQUIRED_TELEMETRY_COLUMNS if c not in out.columns]
    if missing:
        raise ValueError(f"Telemetry missing required columns: {missing}")

    out["timestamp"] = out["timestamp"].astype(str)
    out["node_id"] = out["node_id"].astype(str)
    out["gpu_id"] = out["gpu_id"].astype(str)

    for c in ["temp_c", "power_w", "gpu_util", "mem_util", "fan_pct", "throttle_flag"]:
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")

    for c in ["power_w", "gpu_util", "mem_util", "fan_pct"]:
        if c not in out.columns:
            out[c] = np.nan

    if "throttle_flag" not in out.columns:
        out["throttle_flag"] = 0
    out["throttle_flag"] = out["throttle_flag"].fillna(0).astype(int)

    return out.sort_values(["timestamp", "node_id", "gpu_id"]).reset_index(drop=True)


def load_telemetry_csv(file_or_path) -> pd.DataFrame:
    return validate_telemetry(pd.read_csv(file_or_path))


def generate_sample_topology(rows: int = 3, cols: int = 4) -> pd.DataFrame:
    nodes = []
    idx = 0
    for r in range(rows):
        for c in range(cols):
            nodes.append({
                "node_id": f"gpu-node-{idx:02d}",
                "rack_id": f"rack-{r+1}",
                "row": r,
                "col": c,
                "zone": "cold-aisle-A" if c < cols // 2 else "cold-aisle-B",
            })
            idx += 1
    return pd.DataFrame(nodes)


def validate_topology(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "node_id" not in out.columns:
        raise ValueError("Topology must include node_id")
    out["node_id"] = out["node_id"].astype(str)
    for col in ["rack_id", "zone"]:
        if col not in out.columns:
            out[col] = "unknown"
        out[col] = out[col].fillna("unknown").astype(str)
    for col in ["row", "col"]:
        if col not in out.columns:
            out[col] = np.nan
        out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


def load_topology_csv(file_or_path) -> pd.DataFrame:
    return validate_topology(pd.read_csv(file_or_path))


def generate_sample_telemetry(
    steps: int = 180,
    rows: int = 3,
    cols: int = 4,
    gpus_per_node: int = 4,
    seed: int = 11,
    scenario: str = "hot_aisle_cascade",
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    topology = generate_sample_topology(rows=rows, cols=cols)
    records = []
    center = (rows // 2, cols // 2)

    for t in range(steps):
        for _, topo_row in topology.iterrows():
            node_id = str(topo_row["node_id"])
            r = int(topo_row["row"])
            c = int(topo_row["col"])
            dist = abs(r - center[0]) + abs(c - center[1])

            if scenario == "normal_day":
                workload_boost = 8 * np.sin(t / 30)
                thermal_boost = 0
            elif scenario == "hot_aisle_cascade":
                radius = int(t > 45) + int(t > 85)
                hot = dist <= radius
                workload_boost = 45 if hot else 5
                thermal_boost = max(0, 26 - 7 * dist) if t > 50 else 0
                if 95 <= t <= 135 and hot:
                    workload_boost += 25
                    thermal_boost += 16
            elif scenario == "inference_spike":
                hot = c >= cols // 2 and t > 55
                workload_boost = 50 if hot else 10
                thermal_boost = 20 if hot else 2
            elif scenario == "fan_underperformance":
                hot = r == 1 and t > 60
                workload_boost = 25 if hot else 8
                thermal_boost = 28 if hot else 4
            else:
                workload_boost = 10
                thermal_boost = 0

            for gpu_id in range(gpus_per_node):
                base_util = 35 + rng.normal(0, 6)
                base_power = 130 + rng.normal(0, 12)
                util = np.clip(base_util + workload_boost + rng.normal(0, 8), 0, 100)
                power = np.clip(base_power + 1.6 * util + rng.normal(0, 18), 70, 450)
                temp = 42 + 0.105 * power + 0.11 * util + thermal_boost + rng.normal(0, 2.0)
                fan = np.clip(35 + 0.75 * max(0, temp - 55) + rng.normal(0, 5), 20, 100)
                if scenario == "fan_underperformance" and r == 1 and t > 60:
                    fan = np.clip(fan - 18, 20, 75)
                    temp += 7

                throttle_flag = int(temp >= 91 or (temp >= 87 and util > 92))
                records.append({
                    "timestamp": f"t{t:04d}",
                    "node_id": node_id,
                    "gpu_id": gpu_id,
                    "temp_c": round(float(temp), 2),
                    "power_w": round(float(power), 2),
                    "gpu_util": round(float(util), 2),
                    "mem_util": round(float(np.clip(util + rng.normal(0, 12), 0, 100)), 2),
                    "fan_pct": round(float(fan), 2),
                    "throttle_flag": throttle_flag,
                    "job_id": f"job-{(t // 20) % 9}",
                    "tenant_id": f"tenant-{(gpu_id + c) % 4}",
                })
    return validate_telemetry(pd.DataFrame(records)), validate_topology(topology)


def save_sample_files(output_dir: Path) -> Tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    telemetry, topology = generate_sample_telemetry()
    telem_path = output_dir / "sample_gpu_telemetry.csv"
    topo_path = output_dir / "sample_topology.csv"
    telemetry.to_csv(telem_path, index=False)
    topology.to_csv(topo_path, index=False)
    return telem_path, topo_path
