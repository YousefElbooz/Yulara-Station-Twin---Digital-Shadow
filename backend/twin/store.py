"""
The twin's memory (SQLite, decision Q3): every processed step, the alarms, the closed days,
and the latest state. The API (step 8) only reads from here.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS steps (
    time_utc TEXT PRIMARY KEY,
    measured_kw REAL, expected_kw REAL, ratio REAL, status TEXT,
    ghi_wm2 REAL, poa_wm2 REAL, t_air_c REAL, t_cell_c REAL, wind_ms REAL, wind_dir_deg REAL,
    equipment_temp_c REAL, sun_elevation_deg REAL, src_weather TEXT
);
CREATE TABLE IF NOT EXISTS alarms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT, severity TEXT, confidence TEXT,
    start_utc TEXT, end_utc TEXT, is_open INTEGER,
    message TEXT, recommendation TEXT
);
CREATE TABLE IF NOT EXISTS days (
    date TEXT PRIMARY KEY,
    measured_kwh REAL, expected_kwh REAL, pr_unlimited REAL, pr_smooth REAL,
    soiling_index REAL, pr_vs_month REAL, limit_loss_kwh REAL, health_loss_kwh REAL, outage_loss_kwh REAL
);
CREATE TABLE IF NOT EXISTS predictions (
    time_utc TEXT, model TEXT, kw REAL, PRIMARY KEY (time_utc, model)
);
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT);
"""


class Store:
    def __init__(self, path: Path, reset: bool = False):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(path, check_same_thread=False, timeout=10)
        # WAL: the API reads while the twin writes, without locking each other out
        self.con.execute("PRAGMA journal_mode=WAL")
        if reset:
            # empty the tables instead of deleting the file: on Windows the file can't be deleted while the
            # API has it open, and the twin is restarted from the site's settings panel
            self.con.executescript("DROP TABLE IF EXISTS steps; DROP TABLE IF EXISTS alarms; DROP TABLE IF EXISTS days;"
                                   "DROP TABLE IF EXISTS predictions; DROP TABLE IF EXISTS state;")
        self.con.executescript(SCHEMA)
        self.con.commit()

    def close(self):
        try:
            self.con.commit()
            self.con.close()
        except Exception:  # noqa: BLE001
            pass

    def add_step(self, s: dict):
        cols = ["time_utc", "measured_kw", "expected_kw", "ratio", "status", "ghi_wm2", "poa_wm2", "t_air_c",
                "t_cell_c", "wind_ms", "wind_dir_deg", "equipment_temp_c", "sun_elevation_deg", "src_weather"]
        self.con.execute(f"INSERT OR REPLACE INTO steps ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                         [s.get(c) for c in cols])

    def add_predictions(self, time_utc: str, preds: dict):
        if preds:
            self.con.executemany("INSERT OR REPLACE INTO predictions (time_utc, model, kw) VALUES (?,?,?)",
                                 [(time_utc, k, v) for k, v in preds.items()])

    def open_alarm(self, a: dict) -> int:
        cur = self.con.execute(
            "INSERT INTO alarms (type, severity, confidence, start_utc, end_utc, is_open, message, recommendation) "
            "VALUES (?,?,?,?,NULL,1,?,?)",
            [a["type"], a["severity"], a.get("confidence", "normal"), a["start_utc"], a["message"], a["recommendation"]])
        return cur.lastrowid

    def close_alarm(self, alarm_id: int, end_utc: str):
        self.con.execute("UPDATE alarms SET is_open=0, end_utc=? WHERE id=?", [end_utc, alarm_id])

    def add_day(self, d: dict):
        cols = ["date", "measured_kwh", "expected_kwh", "pr_unlimited", "pr_smooth", "soiling_index",
                "pr_vs_month", "limit_loss_kwh", "health_loss_kwh", "outage_loss_kwh"]
        self.con.execute(f"INSERT OR REPLACE INTO days ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                         [d.get(c) for c in cols])

    def set_state(self, key: str, value):
        self.con.execute("INSERT OR REPLACE INTO state (key, value) VALUES (?, ?)", [key, json.dumps(value, default=str)])

    def get_state(self, key: str):
        row = self.con.execute("SELECT value FROM state WHERE key=?", [key]).fetchone()
        return json.loads(row[0]) if row else None

    def commit(self):
        self.con.commit()


def reader(path: Path) -> sqlite3.Connection:
    """Read-only connection for the API (one per request)."""
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con
