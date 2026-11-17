"""
Step 1b: correct the station GHI sensor after it changed in April 2024.

Finding: the station GHI agreed with ERA5 for 2016 - March 2024, then read about 14% high.
ERA5 and the station already differed by season before the change (ERA5 lower in winter), so the
jump is measured against the SAME calendar month in the years before the change.

Methods (config/data.yaml -> ghi_sensor_correction.method):
  constant  (default, fix of 2026-11-17)  one factor for the whole period after the change
  monthly   (first version)               one factor per month, forcing each month to the
                                          all-year baseline ratio; over-corrects winter
Before the change date nothing is modified. The raw ghi_wm2 stays in the station table.

Reads   data/clean/station_5min.parquet, data/era5/era5_hourly_site_utc.csv, config/data.yaml
Writes  data/clean/ghi_corrected_5min.parquet   ghi_corr_wm2, ghi_corr_factor, flag_ghi_corrected
        docs/ghi_sensor_correction.md          generated report

Usage (from the project folder)
  .venv\\Scripts\\python scripts\\correct_ghi_sensor.py
"""
import os

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]


def hourly_comparison(st_ghi, era5, min_era5):
    """Station hourly mean (hour ending at stamp, like ERA5) next to ERA5, sunny-enough hours only."""
    r = dict(label="right", closed="right")
    hourly = st_ghi.resample("h", **r).mean()
    count = st_ghi.resample("h", **r).count()
    h = pd.DataFrame({"st": hourly[count >= 10]}).join(era5["era5_ghi"], how="inner").dropna()
    return h[h["era5_ghi"] > min_era5]


def main():
    cfg = yaml.safe_load((ROOT / "config" / "data.yaml").read_text(encoding="utf-8"))["ghi_sensor_correction"]
    st = pd.read_parquet(ROOT / "data/clean/station_5min.parquet", columns=["ghi_wm2"])
    era5 = pd.read_csv(ROOT / "data/era5/era5_hourly_site_utc.csv", parse_dates=["time"]).set_index("time")
    era5.index = era5.index.tz_localize("UTC")

    h = hourly_comparison(st["ghi_wm2"], era5, cfg["min_era5_ghi_wm2"])
    month = h.index.tz_convert(None).to_period("M")
    monthly = h.groupby(month).agg(st=("st", "sum"), era5=("era5_ghi", "sum"))
    monthly["ratio"] = monthly["st"] / monthly["era5"]

    start = pd.Period(cfg["from"][:7], "M")
    base = monthly[monthly.index < start]
    after = monthly.index >= start
    # station / ERA5 for each calendar month, before the change
    clim = base.groupby(base.index.month).apply(lambda x: x["st"].sum() / x["era5"].sum())
    all_year = base["st"].sum() / base["era5"].sum()
    noise = (base["ratio"] / base.index.month.map(clim).values).std()

    post = monthly[after].copy()
    post["expected_ratio"] = post.index.month.map(clim).values
    post["jump"] = post["ratio"] / post["expected_ratio"]
    jump_total = post["st"].sum() / (post["era5"] * post["expected_ratio"]).sum()

    method = cfg.get("method", "constant")
    if method == "constant":
        post["factor"] = 1.0 / jump_total
    elif method == "monthly":
        post["factor"] = all_year / post["ratio"]
    else:
        raise ValueError(f"unknown method {method}")
    fill_factor = float(post["factor"].median())

    st_month = st.index.tz_convert(None).to_period("M")
    f = post["factor"].reindex(st_month)
    f = f.where(~(f.isna() & (st_month >= start)), fill_factor).fillna(1.0)
    factor = pd.Series(f.values, index=st.index)
    corrected = pd.DataFrame({
        "ghi_corr_wm2": (st["ghi_wm2"] * factor).astype("float32"),
        "ghi_corr_factor": factor.astype("float32"),
        "flag_ghi_corrected": factor.ne(1.0),
    }, index=st.index)
    corrected.to_parquet(ROOT / cfg["output_file"])

    # what each method would have done, for the record
    monthly_factor = all_year / post["ratio"]
    winter = post.index.month.isin([6, 7, 8])
    over = (post["jump"] * monthly_factor)  # corrected / expected under the monthly method

    L = [
        "# GHI sensor correction (step 1b)",
        "",
        f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC by `scripts/correct_ghi_sensor.py`. Do not edit by hand.",
        "",
        f"**Method in use: `{method}`.** Correction applies from **{cfg['from']}** to the end of the data. "
        "Background and decision record: `docs/notes_sensor_and_fixes.md`.",
        "",
        f"Hours compared: station hourly mean GHI vs ERA5 GHI at the site, ERA5 above {cfg['min_era5_ghi_wm2']} W/m².",
        "",
        "## Station / ERA5 before the change, by calendar month",
        "",
        "| Month | " + " | ".join(str(m) for m in clim.index) + " |",
        "|---|" + "---|" * len(clim),
        "| Ratio | " + " | ".join(f"{v:.3f}" for v in clim.values) + " |",
        "",
        f"All-year ratio before the change: {all_year:.3f}. Normal month-to-month scatter around the calendar-month value: "
        f"±{noise:.3f} (one standard deviation).",
        "",
        "## The jump after the change (ratio ÷ same calendar month before)",
        "",
        "| Month | Station / ERA5 | Expected (same month before) | Jump | Factor applied |",
        "|---|---|---|---|---|",
    ] + [f"| {m} | {r['ratio']:.3f} | {r['expected_ratio']:.3f} | {r['jump']:.3f} | {r['factor']:.3f} |" for m, r in post.iterrows()] + [
        "",
        f"Overall jump: **{jump_total:.3f}** (2024: {post.loc[post.index.year == 2024, 'jump'].mean():.3f}, "
        f"2025 onwards: {post.loc[post.index.year >= 2025, 'jump'].mean():.3f}; scatter ±{post['jump'].std():.3f}). "
        f"Months with no sensor data get factor {fill_factor:.3f}.",
        "",
        f"For comparison, the first method (`monthly`) left June–August corrected GHI at "
        f"{over[winter].mean():.3f} of its expected level, i.e. about {100 * (1 - over[winter].mean()):.0f}% too low.",
        "",
        "Limits: assumes ERA5 itself did not change at the site and that the sensor error is a steady scale factor. "
        "Pyranometer_1 (plane of array) shows no jump in April 2024, which points to the GHI sensor.",
        "",
    ]
    (ROOT / cfg["report_file"]).write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
