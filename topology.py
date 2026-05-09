
from __future__ import annotations

from typing import Dict, Any
import pandas as pd


def merge_topology(telemetry: pd.DataFrame, topology: pd.DataFrame) -> pd.DataFrame:
    t = telemetry.copy()
    topo = topology.copy()
    t["node_id"] = t["node_id"].astype(str)
    topo["node_id"] = topo["node_id"].astype(str)
    cols = ["node_id"]
    for c in ["rack_id", "row", "col", "zone"]:
        if c in topo.columns:
            cols.append(c)
    out = t.merge(topo[cols].drop_duplicates("node_id"), on="node_id", how="left")
    for c in ["rack_id", "zone"]:
        if c not in out.columns:
            out[c] = "unknown"
        out[c] = out[c].fillna("unknown").astype(str)
    return out


def topology_summary(topology: pd.DataFrame) -> Dict[str, Any]:
    return {
        "nodes": int(topology["node_id"].nunique()) if "node_id" in topology.columns else 0,
        "racks": int(topology["rack_id"].nunique()) if "rack_id" in topology.columns else 0,
        "zones": int(topology["zone"].nunique()) if "zone" in topology.columns else 0,
    }
