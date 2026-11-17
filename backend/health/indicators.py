"""
Plant health indicators (step 5): compare what the plant produced with what the calibrated
physics says it should have produced, and turn the gap into named causes.

Daily quantities (local date, ACST):
  pr_unlimited      measured / expected on "unlimited" moments (plant free to follow the sun)
  pr_smooth         trailing rolling median of pr_unlimited (used by the rules below)
  expected_kwh      calibrated physics energy for the day (all daylight)
  health_kwh        expected energy after the plant's own condition: expected * pr_smooth
  health_loss_kwh   expected - health  (ageing, dirt, broken parts)
  limit_loss_kwh    health - measured  (energy the plant could make but did not: limits, curtailment)
  soiling_index     pr_smooth / its highest value in the last N days
Events:
  outage   a sunny day with almost no production while power data exists
  soiling  soiling_index below a threshold for several days
  fault    pr_smooth well below its previous 30-day median for several days

The functions take plain DataFrames so the live twin can call them on recent data too.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

LOCAL = pd.Timedelta(hours=9.5)


def unlimited_mask(df: pd.DataFrame, u: dict) -> pd.Series:
    return (
        (df["sun_elevation_deg"] > u["min_sun_deg"])
        & df["p_expected_cal_kw"].between(u["min_expected_kw"], u["max_expected_kw"])
        & df["p_ac_kw"].notna()
        & ~df["flag_stuck_power"]
        & (df["src_ghi"].astype(str) != "era5")
    )


def daily_table(df: pd.DataFrame, rain_mm: pd.Series, cfg: dict) -> pd.DataFrame:
    """df: 5-min rows with p_ac_kw, p_expected_cal_kw, sun_elevation_deg, flag_stuck_power, src_ghi,
    t_probe1_c, t_probe2_c. rain_mm: daily rain indexed by local date."""
    u = cfg["unlimited"]
    date = (df.index + LOCAL).date
    day = df["sun_elevation_deg"] > 0
    both = day & df["p_ac_kw"].notna() & df["p_expected_cal_kw"].notna()
    unl = unlimited_mask(df, u)

    t = pd.DataFrame({
        "date": date,
        "meas_kwh": df["p_ac_kw"].clip(lower=0).where(both) / 12,
        "exp_kwh": df["p_expected_cal_kw"].where(both) / 12,
        "exp_all_kwh": df["p_expected_cal_kw"].where(day) / 12,
        "meas_unl": df["p_ac_kw"].where(unl),
        "exp_unl": df["p_expected_cal_kw"].where(unl),
        "n_unl": unl.astype(int),
        "day": day.astype(int),
        "both": both.astype(int),
        "probe_max": df[["t_probe1_c", "t_probe2_c"]].max(axis=1),
        "hot": (df[["t_probe1_c", "t_probe2_c"]].max(axis=1) > cfg["equipment_heat"]["alert_above_c"]).astype(int),
    }, index=df.index)
    g = t.groupby("date")
    d = pd.DataFrame({
        "measured_kwh": g["meas_kwh"].sum(min_count=1),
        "expected_kwh": g["exp_kwh"].sum(min_count=1),
        "expected_full_day_kwh": g["exp_all_kwh"].sum(min_count=1),
        "coverage": g["both"].sum() / g["day"].sum().replace(0, np.nan),
        "unlimited_samples": g["n_unl"].sum(),
        "pr_unlimited": g["meas_unl"].sum() / g["exp_unl"].sum(),
        "equipment_temp_max_c": g["probe_max"].max(),
        "equipment_hot_hours": g["hot"].sum() / 12,
    })
    d.index = pd.to_datetime(d.index)
    d.loc[d["unlimited_samples"] < u["min_samples_per_day"], "pr_unlimited"] = np.nan
    d["rain_mm"] = rain_mm.reindex(d.index).fillna(0.0)
    return add_rolling(d, cfg)


def add_rolling(d: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Rolling, history-dependent columns. Uses only past and current days, so the live twin can
    append one closed day to its history and call this again."""
    d = d.copy()
    n = cfg["pr_smoothing_days"]
    d["pr_smooth"] = d["pr_unlimited"].rolling(f"{n}D", min_periods=3).median()
    pr = d["pr_smooth"].clip(upper=1.1)
    d["health_kwh"] = d["expected_kwh"] * pr
    d["health_loss_kwh"] = d["expected_kwh"] - d["health_kwh"]
    d["limit_loss_kwh"] = (d["health_kwh"] - d["measured_kwh"]).clip(lower=0)

    s = cfg["soiling"]
    d["rain_day"] = d["rain_mm"] >= s["rain_mm_per_day"]
    clean_ref = d["pr_smooth"].rolling(f"{s['clean_reference_days']}D", min_periods=5).max()
    d["soiling_index"] = d["pr_smooth"] / clean_ref

    f = cfg["fault"]
    ref = d["pr_smooth"].rolling("30D", min_periods=10).median().shift(1)
    d["pr_vs_month"] = d["pr_smooth"] / ref
    d["outage_day"] = (
        (d["expected_full_day_kwh"] >= f["outage_expected_kwh"])
        & (d["coverage"] >= 0.8)
        & (d["measured_kwh"] < f["outage_measured_share"] * d["expected_kwh"])
    )
    # a stopped plant is an outage, not output limiting: book that day's gap separately
    d["outage_loss_kwh"] = (d["expected_kwh"] - d["measured_kwh"]).where(d["outage_day"], 0.0)
    d.loc[d["outage_day"], "limit_loss_kwh"] = 0.0
    return d


def runs(flag: pd.Series, min_len: int) -> list[tuple[pd.Timestamp, pd.Timestamp, int]]:
    """Consecutive True stretches of at least min_len days: (start, end, length)."""
    flag = flag.fillna(False).astype(bool)
    out, start, prev = [], None, None
    for ts, v in flag.items():
        if v and start is None:
            start = ts
        if v:
            prev = ts
        if not v and start is not None:
            n = (prev - start).days + 1
            if n >= min_len:
                out.append((start, prev, n))
            start = None
    if start is not None:
        n = (prev - start).days + 1
        if n >= min_len:
            out.append((start, prev, n))
    return out


def events(d: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    rows = []
    for a, b, n in runs(d["outage_day"], 1):
        rows.append(("outage", a, b, n, float(d.loc[a:b, "expected_kwh"].sum())))
    s = cfg["soiling"]
    for a, b, n in runs(d["soiling_index"] < s["alert_below"], s["min_days"]):
        rows.append(("soiling", a, b, n, float(d.loc[a:b, "soiling_index"].min())))
    f = cfg["fault"]
    for a, b, n in runs(d["pr_vs_month"] < f["drop_below"], f["min_days"]):
        rows.append(("fault", a, b, n, float(d.loc[a:b, "pr_vs_month"].min())))
    ev = pd.DataFrame(rows, columns=["type", "start", "end", "days", "value"])
    return ev.sort_values("start").reset_index(drop=True)
