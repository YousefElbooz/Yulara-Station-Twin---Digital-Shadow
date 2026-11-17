"""
Step 3: run the physics model on the whole station history and check it on clear days.

Reads   data/clean/station_5min.parquet, config/station.yaml, config/physics.yaml
Writes  data/clean/physics_5min.parquet   (same 5-min UTC index, physics columns)
        docs/physics_validation.md        (generated report; do not edit by hand)

Usage (from the project folder)
  .venv\\Scripts\\python scripts\\simulate_physics.py
"""
import os

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.physics.pv_chain import simulate  # noqa: E402


def load_yaml(name):
    return yaml.safe_load((ROOT / "config" / name).read_text(encoding="utf-8"))


def clear_days(df, cfg):
    """Daily table with the clear-sky criteria; df has ghi_wm2, ghi_clearsky_wm2, sun_elevation_deg."""
    day = df[df["sun_elevation_deg"] > 0]
    local_date = (day.index + pd.Timedelta(hours=9.5)).date
    g, gc = day["ghi_wm2"], day["ghi_clearsky_wm2"]
    dt = 5.0
    vi_num = np.sqrt(g.diff() ** 2 + dt ** 2)
    vi_den = np.sqrt(gc.diff() ** 2 + dt ** 2)
    t = pd.DataFrame({"g": g, "gc": gc, "num": vi_num, "den": vi_den, "present": g.notna()}, index=day.index)
    t["date"] = local_date
    d = t.groupby("date").agg(g=("g", "sum"), gc=("gc", "sum"), num=("num", "sum"), den=("den", "sum"),
                              present=("present", "mean"))
    d["energy_ratio"] = d["g"] / d["gc"]
    d["vi"] = d["num"] / d["den"]
    lo, hi = cfg["energy_ratio"]
    d["clear"] = (d["present"] >= cfg["min_data_fraction"]) & d["energy_ratio"].between(lo, hi) & (d["vi"] <= cfg["max_variability_index"])
    return d


def load_weather(phys):
    """Station table plus the weather the physics uses (steps 1b and 1c):
    corrected GHI, with ERA5 filling sensor outages. Raw sensor columns stay for comparisons."""
    st = pd.read_parquet(ROOT / phys["input_file"])
    wm = ROOT / "data/clean/weather_model_5min.parquet"
    if wm.exists():
        st = st.join(pd.read_parquet(wm))
    else:
        st["ghi_model_wm2"], st["t_air_model_c"], st["wind_model_ms"] = st["ghi_wm2"], st["t_air_c"], st["wind_ms"]
        st["src_ghi"] = "station"
    return st


def model_inputs(chunk):
    return chunk[["ghi_model_wm2", "t_air_model_c", "wind_model_ms"]].rename(
        columns={"ghi_model_wm2": "ghi_wm2", "t_air_model_c": "t_air_c", "wind_model_ms": "wind_ms"})


def main():
    station, phys = load_yaml("station.yaml"), load_yaml("physics.yaml")
    st = load_weather(phys)

    parts = []
    for year, chunk in st.groupby(st.index.year):
        parts.append(simulate(model_inputs(chunk), station, phys))
        print(f"simulated {year}: {len(chunk):,} steps", flush=True)
    sim = pd.concat(parts)
    out = ROOT / phys["output_file"]
    sim.to_parquet(out)
    print(f"saved {out} ({out.stat().st_size / 1e6:.1f} MB)")

    # ---------------- validation ----------------
    # validation uses measured (or corrected) station GHI only, never the ERA5-filled steps
    st["ghi_valid_wm2"] = st["ghi_model_wm2"].where(st["src_ghi"].astype(str) != "era5")
    df = st[["p_ac_kw", "ghi_valid_wm2", "pyrano1_wm2", "sun_elevation_deg", "flag_stuck_power"]].rename(
        columns={"ghi_valid_wm2": "ghi_wm2"}).join(
        sim[["p_expected_kw", "poa_global_wm2", "ghi_clearsky_wm2", "t_cell_c"]])
    df["local_hour"] = (df.index + pd.Timedelta(hours=9.5)).hour
    df["month"] = (df.index + pd.Timedelta(hours=9.5)).month

    days = clear_days(df, phys["clear_day"])
    clear_dates = set(days.index[days["clear"]])
    local_date = (df.index + pd.Timedelta(hours=9.5)).date
    on_clear = pd.Series(local_date, index=df.index).isin(clear_dates)

    ok = on_clear & df["p_ac_kw"].notna() & (df["p_expected_kw"] > 50)
    c = df[ok].copy()
    c["ratio"] = c["p_ac_kw"] / c["p_expected_kw"]
    season = c["month"].map({12: "summer (Dec-Feb)", 1: "summer (Dec-Feb)", 2: "summer (Dec-Feb)",
                             6: "winter (Jun-Aug)", 7: "winter (Jun-Aug)", 8: "winter (Jun-Aug)"})
    by_hour = c.assign(season=season).dropna(subset=["season"]).groupby(["season", "local_hour"])["ratio"].median().unstack(0)

    low = c[c["p_expected_kw"] < 300]
    morning = low[low["local_hour"] < 12]["ratio"].median()
    afternoon = low[low["local_hour"] >= 13]["ratio"].median()

    # annual expected vs measured (full years, steps where both exist)
    both = df[df["p_ac_kw"].notna() & df["p_expected_kw"].notna()]
    yr = both.groupby(both.index.year).agg(measured=("p_ac_kw", lambda s: s.clip(lower=0).sum() / 12e3),
                                           expected=("p_expected_kw", lambda s: s.sum() / 12e3))
    yr["measured_pct_of_expected"] = 100 * yr["measured"] / yr["expected"]
    coverage = df.groupby(df.index.year)["p_expected_kw"].apply(lambda s: s[df.loc[s.index, "sun_elevation_deg"] > 0].notna().mean())

    # what is Pyranometer_1? compare with GHI and modelled POA near solar noon on clear days
    noon = df[on_clear & (df["sun_elevation_deg"] > 0)]
    noon = noon[noon.groupby((noon.index + pd.Timedelta(hours=9.5)).date)["sun_elevation_deg"].transform("max") - noon["sun_elevation_deg"] < 2]
    py = noon.dropna(subset=["pyrano1_wm2", "ghi_wm2"]).groupby("month").agg(
        ghi=("ghi_wm2", "median"), pyrano1=("pyrano1_wm2", "median"), poa_model=("poa_global_wm2", "median"))

    lines = [
        "# Physics model validation (step 3, version 0: not calibrated)",
        "",
        f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC by `scripts/simulate_physics.py`. Do not edit by hand.",
        "",
        "Model: " + ", ".join(f"{k} = {phys[k]}" for k in ["decomposition", "transposition", "albedo", "iam", "temperature_model", "dc_loss_fraction"])
        + f". Station: {station['array']['dc_capacity_kw']} kW DC, tilt {station['array']['tilt_deg']} deg, "
          f"azimuth {station['array']['azimuth_deg']} deg (north), AC limit {station['inverter']['ac_capacity_kw']} kW (calculated).",
        "",
        "## Clear days",
        "",
        f"{len(clear_dates):,} clear days out of {len(days):,} days with data "
        f"(criteria in `config/physics.yaml`).",
        "",
        "## Measured / expected power on clear days, median by local hour",
        "",
        "Only steps with expected power above 50 kW. A model that is right and a plant that is free to "
        "produce would give a flat line near 1.",
        "",
        "| Local hour (ACST) | " + " | ".join(by_hour.columns) + " |",
        "|---|" + "---|" * len(by_hour.columns),
    ]
    for h, row in by_hour.iterrows():
        lines.append(f"| {h:02d}:00 | " + " | ".join("–" if pd.isna(v) else f"{v:.2f}" for v in row) + " |")
    lines += [
        "",
        "## When the plant is far below any limit (expected power under 300 kW, clear days)",
        "",
        f"- Median measured / expected, morning: **{morning:.3f}**",
        f"- Median measured / expected, afternoon: **{afternoon:.3f}**",
        "",
        "## Yearly energy, measured vs expected (only steps where both exist)",
        "",
        "| Year | Measured MWh | Expected MWh | Measured % | Daylight coverage of the model |",
        "|---|---|---|---|---|",
    ]
    for y, r in yr.iterrows():
        lines.append(f"| {y} | {r['measured']:,.0f} | {r['expected']:,.0f} | {r['measured_pct_of_expected']:.0f}% | {100 * coverage.get(y, np.nan):.0f}% |")
    lines += [
        "",
        "## What does Pyranometer_1 measure? (clear days, within 2 deg of the day's highest sun)",
        "",
        "| Month | GHI (station) | Pyranometer_1 | Modelled plane-of-array |",
        "|---|---|---|---|",
    ]
    for m, r in py.iterrows():
        lines.append(f"| {m} | {r['ghi']:.0f} | {r['pyrano1']:.0f} | {r['poa_model']:.0f} |")
    lines.append("")

    rep = ROOT / phys["report_file"]
    rep.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
