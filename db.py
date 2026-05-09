
"""
SQLite persistence layer for V3.

Stores:
- runs
- risk timeline rows
- alerts
- recommendations
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Any, Optional
import json
import sqlite3
import time
import pandas as pd


def connect(db_path: str = "data/fcct_guard.db") -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    init_db(conn)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS runs (
        run_id TEXT PRIMARY KEY,
        created_at REAL,
        source TEXT,
        config_json TEXT,
        calibration_json TEXT,
        summary_json TEXT
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS risk_timeline (
        run_id TEXT,
        timestamp TEXT,
        risk_score REAL,
        status TEXT,
        max_scale INTEGER,
        coherent_pairs INTEGER,
        risky_pairs INTEGER,
        critical_components INTEGER,
        throttle_events INTEGER,
        risky_components TEXT
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS alerts (
        run_id TEXT,
        timestamp TEXT,
        severity TEXT,
        risk_score REAL,
        message TEXT
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS recommendations (
        run_id TEXT,
        priority TEXT,
        scope TEXT,
        target TEXT,
        reason TEXT,
        recommendation TEXT
    )
    """)
    conn.commit()


def save_run(
    conn: sqlite3.Connection,
    run_id: str,
    source: str,
    config: Dict[str, Any],
    calibration: Dict[str, Any],
    summary: Dict[str, Any],
    risk_timeline: pd.DataFrame,
    alerts: pd.DataFrame,
    recommendations: pd.DataFrame,
) -> None:
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO runs VALUES (?, ?, ?, ?, ?, ?)",
        (run_id, time.time(), source, json.dumps(config), json.dumps(calibration), json.dumps(summary)),
    )

    cur.execute("DELETE FROM risk_timeline WHERE run_id=?", (run_id,))
    for _, r in risk_timeline.iterrows():
        cur.execute(
            "INSERT INTO risk_timeline VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                str(r.get("timestamp", "")),
                float(r.get("risk_score", 0.0)),
                str(r.get("status", "")),
                int(r.get("max_scale", 0)),
                int(r.get("coherent_pairs", 0)),
                int(r.get("risky_pairs", 0)),
                int(r.get("critical_components", 0)),
                int(r.get("throttle_events", 0)),
                str(r.get("risky_components", "")),
            ),
        )

    cur.execute("DELETE FROM alerts WHERE run_id=?", (run_id,))
    for _, r in alerts.iterrows():
        cur.execute(
            "INSERT INTO alerts VALUES (?, ?, ?, ?, ?)",
            (run_id, str(r.get("timestamp", "")), str(r.get("severity", "")), float(r.get("risk_score", 0.0)), str(r.get("message", ""))),
        )

    cur.execute("DELETE FROM recommendations WHERE run_id=?", (run_id,))
    for _, r in recommendations.iterrows():
        cur.execute(
            "INSERT INTO recommendations VALUES (?, ?, ?, ?, ?, ?)",
            (
                run_id,
                str(r.get("priority", "")),
                str(r.get("scope", "")),
                str(r.get("target", "")),
                str(r.get("reason", "")),
                str(r.get("recommendation", "")),
            ),
        )

    conn.commit()


def list_runs(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query("SELECT run_id, datetime(created_at, 'unixepoch') AS created_at, source, summary_json FROM runs ORDER BY created_at DESC", conn)


def load_table(conn: sqlite3.Connection, table: str, run_id: Optional[str] = None) -> pd.DataFrame:
    if table not in {"runs", "risk_timeline", "alerts", "recommendations"}:
        raise ValueError("invalid table")
    if run_id is None:
        return pd.read_sql_query(f"SELECT * FROM {table}", conn)
    return pd.read_sql_query(f"SELECT * FROM {table} WHERE run_id=?", conn, params=(run_id,))
