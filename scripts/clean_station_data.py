"""
Step 1: clean the DKASC station file into the canonical 5-minute table.

Reads   data/raw/5-Site_DG-PV1-DB-DG-M1A.csv          (ACST timestamps, raw units)
Writes  data/clean/station_5min.parquet                (UTC, regular 5-min grid, flags)
        docs/quality_report_station.md                 (what was changed and how much)

Rules live in config/data.yaml; the table shape is described in docs/data_contract.md.

Usage (from the project folder)
  .venv\\Scripts\\python scripts\\clean_station_data.py
"""
import os

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")  # avoids out-of-memory on this machine

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pvlib
import yaml

ROOT = Path(__file__).resolve().parents[1]


def load_config():
    data = yaml.safe_load((ROOT / "config" / "data.yaml").read_text(encoding="utf-8"))
    station = yaml.safe_load((ROOT / "config" / "station.yaml").read_text(encoding="utf-8"))
    return data, station


def stuck_runs(p, eligible, tol, min_steps):
    """True where p belongs to a run of >= min_steps consecutive eligible values within tol of each other."""
    same = eligible & eligible.shift(1, fill_value=False) & (p.diff().abs() <= tol)
    run_id = (~same).cumsum()                      # a new id starts wherever the chain breaks
    run_len = same.groupby(run_id).transform("size")
    in_run = same & (run_len + 1 >= min_steps)     # k equal steps = k + 1 equal values
    # include the first value of each qualifying run (the one before the first 'same')
    return in_run | in_run.shift(-1, fill_value=False) & eligible


def main():
    cfg, station = load_config()
    raw_path = ROOT / cfg["raw_file"]
    colmap = cfg["columns"]
    step = pd.Timedelta(minutes=cfg["interval_minutes"])
    offset = pd.Timedelta(hours=station["location"]["utc_offset_hours"])

    raw = pd.read_csv(raw_path, usecols=["timestamp", *colmap], parse_dates=["timestamp"])
    n_raw = len(raw)
    raw = raw.sort_values("timestamp")
    n_dup = int(raw["timestamp"].duplicated().sum())
    raw = raw.drop_duplicates("timestamp", keep="last")

    raw["time_utc"] = (raw["timestamp"] - offset).dt.tz_localize("UTC")
    df = raw.drop(columns="timestamp").rename(columns=colmap).set_index("time_utc").astype("float64")

    gaps = df.index.to_series().diff().dropna()
    n_gaps = int((gaps > step * 1.5).sum())
    biggest_gap = gaps.max()
    biggest_gap_at = gaps.idxmax()

    # 1. sentinel values -> missing
    sentinel = df < cfg["sentinel_below"]
    n_sentinel = sentinel.sum()
    df = df.mask(sentinel)

    # 2. out-of-range values -> missing, counted as bad sensor
    bad = pd.DataFrame(False, index=df.index, columns=df.columns)
    for col, (lo, hi) in cfg["valid_range"].items():
        bad[col] = df[col].notna() & ((df[col] < lo) | (df[col] > hi))
    n_bad = bad.sum()
    df = df.mask(bad)

    # 3. regular grid: insert the missing 5-min steps
    full = pd.date_range(df.index.min(), df.index.max(), freq=step, tz="UTC", name="time_utc")
    flag_gap = ~full.isin(df.index)
    df = df.reindex(full)
    bad = bad.reindex(full, fill_value=False)

    # 4. sun position and flags
    loc = station["location"]
    sp = pvlib.solarposition.get_solarposition(full, loc["latitude"], loc["longitude"], altitude=loc["altitude_m"])
    df["sun_elevation_deg"] = sp["apparent_elevation"].astype("float32")
    df["flag_gap"] = flag_gap
    df["flag_missing_power"] = df["p_ac_kw"].isna()
    df["flag_night"] = df["sun_elevation_deg"] < cfg["night_sun_elevation_deg"]
    df["flag_bad_sensor"] = bad.any(axis=1)
    st = cfg["stuck"]
    eligible = (~df["flag_night"]) & df["p_ac_kw"].notna() & (df["p_ac_kw"] > st["min_kw"])
    df["flag_stuck_power"] = stuck_runs(df["p_ac_kw"], eligible, st["tolerance_kw"], st["min_steps"])

    out = ROOT / cfg["clean_file"]
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out)

    # ---------------- quality report ----------------
    day = ~df["flag_night"]
    daytime_power = int((day & df["p_ac_kw"].notna()).sum())
    stuck = df["flag_stuck_power"]
    stuck_vals = df.loc[stuck, "p_ac_kw"].round(-1).value_counts().head(5)
    energy_kwh = float(df["p_ac_kw"].clip(lower=0).sum() * cfg["interval_minutes"] / 60)

    lines = [
        "# Quality report: station data after cleaning (step 1)",
        "",
        f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC by `scripts/clean_station_data.py` "
        "from `config/data.yaml`. Do not edit by hand.",
        "",
        "## Rows and time",
        "",
        "| | Value |",
        "|---|---|",
        f"| Rows in raw file | {n_raw:,} |",
        f"| Duplicate timestamps dropped | {n_dup} |",
        f"| Range (UTC) | {df.index.min()} to {df.index.max()} |",
        f"| Rows on the regular 5-min grid | {len(df):,} |",
        f"| Steps added as gaps (`flag_gap`) | {int(flag_gap.sum()):,} |",
        f"| Gaps longer than 7.5 min in the raw file | {n_gaps} |",
        f"| Biggest gap | {biggest_gap} after {biggest_gap_at - step:%Y-%m-%d %H:%M} UTC |",
        "",
        "## Values set to missing, per column",
        "",
        "| Column | Sentinel (−9e9) | Out of range (bad sensor) | Missing after cleaning | Missing % |",
        "|---|---|---|---|---|",
    ]
    for raw_name, col in colmap.items():
        miss = int(df[col].isna().sum())
        lines.append(f"| `{col}` | {int(n_sentinel[col]):,} | {int(n_bad[col]):,} | {miss:,} | {100 * miss / len(df):.2f}% |")
    lines += [
        "",
        "## Flags",
        "",
        "| Flag | Rows | % of grid |",
        "|---|---|---|",
    ]
    for f in ["flag_gap", "flag_missing_power", "flag_night", "flag_bad_sensor", "flag_stuck_power"]:
        n = int(df[f].sum())
        lines.append(f"| `{f}` | {n:,} | {100 * n / len(df):.2f}% |")
    lines += [
        "",
        f"`flag_stuck_power` covers {100 * stuck.sum() / max(daytime_power, 1):.2f}% of daytime rows that have power. "
        "Most common stuck values (rounded to 10 kW):",
        "",
        "| Power (kW) | Rows |",
        "|---|---|",
    ]
    for v, n in stuck_vals.items():
        lines.append(f"| {v:.0f} | {n:,} |")
    lines += [
        "",
        "## Cross-checks",
        "",
        f"- Energy from positive power: {energy_kwh:,.1f} kWh (team EDA report: 10,395,853.5 kWh).",
        f"- Max power: {df['p_ac_kw'].max():.2f} kW (DC rating 1,058.4 kW).",
        f"- Night rows with power above 1 kW: {int((df['flag_night'] & (df['p_ac_kw'] > 1)).sum()):,}.",
        "",
    ]
    report = ROOT / cfg["report_file"]
    report.write_text("\n".join(lines), encoding="utf-8")
    print(f"saved {out} ({out.stat().st_size / 1e6:.1f} MB) and {report}")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
