
"""
FCCT GPU Cascade Guard V3 - core mathematical utilities.

Commercial deployable core:
- lambda_r solver: lambda^(r+h) = lambda^r + 1
- symbolic S0-S5 mapping
- FCCT cascade energy
- topology-aware coherent pair detection
- projected symbolic cascade map
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any, List, Tuple, Iterable, Set

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class FCCTConfig:
    coherence_radius: int = 1
    growth_height: int = 1
    max_scale: int = 5
    risk_trigger: float = 0.45
    min_risky_scale: int = 2


@dataclass(frozen=True)
class ScaleCalibration:
    thresholds: Tuple[float, float, float, float, float]
    method: str
    metric_name: str
    explanation: str


def solve_lambda_r(r: int, h: int = 1, tol: float = 1e-10, max_iter: int = 200) -> float:
    if r < 0:
        raise ValueError("coherence radius r must be >= 0")
    if h < 1:
        raise ValueError("growth height h must be >= 1")

    lo = 1.0 + 1e-12
    hi = 2.0

    def f(x: float) -> float:
        return x ** (r + h) - x ** r - 1.0

    while f(hi) < 0:
        hi *= 2.0

    for _ in range(max_iter):
        mid = (lo + hi) / 2.0
        if f(mid) < 0:
            lo = mid
        else:
            hi = mid
        if hi - lo < tol:
            break
    return float((lo + hi) / 2.0)


def assign_scale(values: pd.Series, calibration: ScaleCalibration, max_scale: int = 5) -> pd.Series:
    thresholds = np.array(calibration.thresholds, dtype=float)
    scales = np.digitize(values.astype(float).to_numpy(), thresholds, right=False)
    return pd.Series(np.clip(scales, 0, max_scale), index=values.index, dtype="int64")


def scale_counts(scales: Iterable[int], max_scale: int = 5) -> np.ndarray:
    counts = np.zeros(max_scale + 1, dtype=int)
    for s in scales:
        idx = int(np.clip(int(s), 0, max_scale))
        counts[idx] += 1
    return counts


def cascade_energy_from_scales(scales: Iterable[int], lam: float, max_scale: int = 5) -> float:
    counts = scale_counts(scales, max_scale=max_scale)
    powers = np.array([lam ** k for k in range(max_scale + 1)], dtype=float)
    return float(np.dot(counts, powers))


def normalize_energy(energy: float, n_components: int, lam: float, max_scale: int = 5) -> float:
    if n_components <= 0:
        return 0.0
    max_possible = n_components * (lam ** max_scale)
    return float(energy / max_possible)


def component_id(node_id: object, gpu_id: object) -> str:
    return f"{node_id}::gpu{gpu_id}"


def ensure_component_id(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "component_id" not in out.columns:
        out["component_id"] = [
            component_id(n, g) for n, g in zip(out["node_id"].astype(str), out["gpu_id"].astype(str))
        ]
    return out


def build_edges_from_topology(topology: pd.DataFrame, components: pd.DataFrame) -> List[Tuple[str, str]]:
    topo = topology.copy()
    comps = ensure_component_id(components)

    if "node_id" not in topo.columns:
        raise ValueError("topology must include node_id")

    topo["node_id"] = topo["node_id"].astype(str)
    comps["node_id"] = comps["node_id"].astype(str)

    node_to_comps: Dict[str, List[str]] = comps.groupby("node_id")["component_id"].apply(list).to_dict()
    edges: Set[Tuple[str, str]] = set()

    def add_edge(a: str, b: str) -> None:
        if a != b:
            edges.add(tuple(sorted((a, b))))

    # GPUs on same node are neighbors.
    for ids in node_to_comps.values():
        ids = sorted(set(ids))
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                add_edge(ids[i], ids[j])

    topo_index = topo.drop_duplicates("node_id").set_index("node_id")

    # Physical adjacency through row/col and same zone.
    if {"row", "col"}.issubset(topo_index.columns):
        rows = pd.to_numeric(topo_index["row"], errors="coerce")
        cols = pd.to_numeric(topo_index["col"], errors="coerce")
        nodes = list(topo_index.index)

        for i in range(len(nodes)):
            for j in range(i + 1, len(nodes)):
                a, b = nodes[i], nodes[j]
                if pd.isna(rows.loc[a]) or pd.isna(rows.loc[b]) or pd.isna(cols.loc[a]) or pd.isna(cols.loc[b]):
                    continue
                manhattan = abs(rows.loc[a] - rows.loc[b]) + abs(cols.loc[a] - cols.loc[b])
                same_zone = True
                if "zone" in topo_index.columns:
                    same_zone = str(topo_index.loc[a, "zone"]) == str(topo_index.loc[b, "zone"])
                if manhattan == 1 and same_zone:
                    for ca in node_to_comps.get(a, []):
                        for cb in node_to_comps.get(b, []):
                            add_edge(ca, cb)

    # Same-rack relation.
    if "rack_id" in topo_index.columns:
        for _, node_indexes in topo_index.groupby("rack_id").groups.items():
            nodes = list(node_indexes)
            for i in range(len(nodes)):
                for j in range(i + 1, len(nodes)):
                    same_zone = True
                    if "zone" in topo_index.columns:
                        same_zone = str(topo_index.loc[nodes[i], "zone"]) == str(topo_index.loc[nodes[j], "zone"])
                    if same_zone:
                        for ca in node_to_comps.get(nodes[i], []):
                            for cb in node_to_comps.get(nodes[j], []):
                                add_edge(ca, cb)

    return sorted(edges)


def coherent_pairs(
    frame: pd.DataFrame,
    edges: List[Tuple[str, str]],
    r: int,
    min_scale: int = 1,
) -> List[Tuple[str, str, int, int]]:
    f = ensure_component_id(frame)
    scale_map = f.set_index("component_id")["scale"].astype(int).to_dict()
    pairs: List[Tuple[str, str, int, int]] = []
    for a, b in edges:
        if a not in scale_map or b not in scale_map:
            continue
        sa, sb = int(scale_map[a]), int(scale_map[b])
        if sa >= min_scale and sb >= min_scale and abs(sa - sb) <= r:
            pairs.append((a, b, sa, sb))
    return pairs


def projected_fusion_scales(
    frame: pd.DataFrame,
    edges: List[Tuple[str, str]],
    r: int,
    max_scale: int = 5,
) -> pd.Series:
    f = ensure_component_id(frame)
    scales = f.set_index("component_id")["scale"].astype(int).to_dict()
    projected = dict(scales)

    for a, b in edges:
        if a not in scales or b not in scales:
            continue
        sa, sb = int(scales[a]), int(scales[b])
        if sa > 0 and sb > 0 and abs(sa - sb) <= r:
            fused = min(max(sa, sb) + 1, max_scale)
            projected[a] = max(projected[a], fused)
            projected[b] = max(projected[b], fused)

    return pd.Series(projected, name="projected_scale")


def risk_for_frame(
    frame: pd.DataFrame,
    edges: List[Tuple[str, str]],
    config: FCCTConfig,
) -> Dict[str, Any]:
    f = ensure_component_id(frame)
    lam = solve_lambda_r(config.coherence_radius, config.growth_height)

    current_energy = cascade_energy_from_scales(f["scale"], lam, config.max_scale)
    projected = projected_fusion_scales(f, edges, config.coherence_radius, config.max_scale)
    projected_energy = cascade_energy_from_scales(projected.values, lam, config.max_scale)

    n = len(f)
    coherent = coherent_pairs(f, edges, config.coherence_radius, min_scale=1)
    risky = coherent_pairs(f, edges, config.coherence_radius, min_scale=config.min_risky_scale)

    risky_components: Set[str] = set()
    for a, b, _, _ in risky:
        risky_components.add(a)
        risky_components.add(b)

    score = normalize_energy(projected_energy, n, lam, config.max_scale)

    return {
        "lambda_r": lam,
        "current_energy": current_energy,
        "projected_energy": projected_energy,
        "current_energy_norm": normalize_energy(current_energy, n, lam, config.max_scale),
        "risk_score": score,
        "coherent_pairs": len(coherent),
        "risky_pairs": len(risky),
        "risky_components": sorted(risky_components),
        "max_scale": int(f["scale"].max()) if len(f) else 0,
        "mean_scale": float(f["scale"].mean()) if len(f) else 0.0,
        "critical_components": int((f["scale"] >= config.max_scale).sum()) if len(f) else 0,
        "status": "ALERT" if score >= config.risk_trigger else "WATCH",
    }
