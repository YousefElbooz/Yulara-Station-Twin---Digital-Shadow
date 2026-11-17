"""
Step 5: plant health indicators over the whole history.

Reads   data/clean/station_5min.parquet, data/clean/weather_model_5min.parquet,
        data/clean/physics_5min.parquet (p_expected_cal_kw), data/era5/era5_hourly_site_utc.csv,
        config/twin.yaml
Writes  data/clean/health_daily.parquet     one row per local day
        data/clean/health_events.csv        outage / soiling / fault events
        docs/health_report.md               generated report

Usage (from the project folder)
  .venv\\Scripts\\python scripts\\compute_health.py
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
from backend.health.indicators import LOCAL, daily_table, events, unlimited_mask  # noqa: E402

# DKASC "Notes on the data" (https://dkasolarcentre.com.au/download/notes-on-the-data), read 2026-11-17.
# The inverter replacements (Dec 2022, Feb 2023) and the 24-30 Jan 2023 outage are at DKASC Alice Springs,
# not Yulara, so they cannot be used to test this plant. These are the notes that name Yulara:
KNOWN = [
    ("30 Jan 2023: Yulara weather and source data had intermittent outages 'over recent months'", "2022-10-01", "2023-01-30"),
    ("6-13 Oct 2023: website maintenance, Yulara datasets re-syncing", "2023-07-18", "2023-10-13"),
]


def main():
    cfg = yaml.safe_load((ROOT / "config" / "twin.yaml").read_text(encoding="utf-8"))["health"]
    st = pd.read_parquet(ROOT / "data/clean/station_5min.parquet",
                         columns=["p_ac_kw", "sun_elevation_deg", "flag_stuck_power", "t_probe1_c", "t_probe2_c"])
    wm = pd.read_parquet(ROOT / "data/clean/weather_model_5min.parquet", columns=["src_ghi"])
    ph = pd.read_parquet(ROOT / "data/clean/physics_5min.parquet", columns=["p_expected_cal_kw", "t_cell_c"])
    df = st.join(wm).join(ph)

    era5 = pd.read_csv(ROOT / "data/era5/era5_hourly_site_utc.csv", parse_dates=["time"]).set_index("time")
    rain = era5["era5_precip_mm"].groupby((era5.index + LOCAL).date).sum()
    rain.index = pd.to_datetime(rain.index)

    d = daily_table(df, rain, cfg)
    ev = events(d, cfg)
    d.to_parquet(ROOT / cfg["output_file"])
    ev.to_csv(ROOT / "data/clean/health_events.csv", index=False)

    # ---------- summaries ----------
    y = d.groupby(d.index.year).agg(
        expected=("expected_kwh", "sum"), measured=("measured_kwh", "sum"),
        health_loss=("health_loss_kwh", "sum"), limit_loss=("limit_loss_kwh", "sum"),
        outage_loss=("outage_loss_kwh", "sum"),
        pr=("pr_unlimited", "median"), outage_days=("outage_day", "sum"))
    y[["expected", "measured", "health_loss", "limit_loss", "outage_loss"]] /= 1000

    m = d[(d.index >= "2022-07-01") & (d.index < "2026-01-01")]
    mon = m.groupby(m.index.to_period("M")).agg(pr=("pr_unlimited", "median"), days=("pr_unlimited", "count"),
                                                coverage=("coverage", "mean"),
                                                limit_share=("limit_loss_kwh", "sum"), exp=("expected_kwh", "sum"))
    mon["limit_share"] = mon["limit_share"] / mon["exp"]

    # rain: smoothed PR 3 days after minus 3 days before, rain days vs all days
    pr = d["pr_unlimited"]
    after = pr.rolling("3D").mean().shift(-3, freq="D").reindex(d.index)
    before = pr.rolling("3D").mean().shift(1, freq="D").reindex(d.index)
    change = (after - before)
    rain_change = change[d["rain_day"]].mean()
    all_change = change.mean()
    n_rain = int(d["rain_day"].sum())

    # temperature check on unlimited moments: does measured/expected fall as cells get hotter?
    unl = unlimited_mask(df, cfg["unlimited"])
    u = df[unl & df["t_cell_c"].notna()]
    ratio = u["p_ac_kw"] / u["p_expected_cal_kw"]
    keep = ratio.between(0.5, 1.5)
    slope = np.polyfit(u["t_cell_c"][keep], ratio[keep], 1)[0] if keep.sum() > 100 else np.nan
    tc_range = u["t_cell_c"][keep].quantile([0.05, 0.95]).values

    counts = ev.groupby([ev["start"].dt.year, "type"]).size().unstack(fill_value=0) if len(ev) else pd.DataFrame()

    def overlap(a, b):
        a, b = pd.Timestamp(a), pd.Timestamp(b)
        hit = ev[(ev["start"] <= b) & (ev["end"] >= a)]
        cov = d.loc[a:b, "coverage"].mean()
        return hit, cov

    L = [
        "# Plant health report (step 5)",
        "",
        f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC by `scripts/compute_health.py`. Do not edit by hand. "
        "Rules and thresholds: `config/twin.yaml` → `health`.",
        "",
        "## Where the energy went, by year",
        "",
        "Only daylight steps where both the measurement and the physics exist. "
        "Health loss = the plant's own condition (ageing, dirt, broken parts). "
        "Limit loss = energy the plant could have made in its condition but did not (output held back).",
        "",
        "| Year | Physics allows (MWh) | Measured (MWh) | Health loss | Limit loss | Outage loss | Median daily PR | Outage days |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for yr, r in y.iterrows():
        e = r["expected"]
        L.append(f"| {yr} | {e:,.0f} | {r['measured']:,.0f} | {r['health_loss']:,.0f} ({100 * r['health_loss'] / e:.0f}%) | "
                 f"{r['limit_loss']:,.0f} ({100 * r['limit_loss'] / e:.0f}%) | {r['outage_loss']:,.0f} ({100 * r['outage_loss'] / e:.0f}%) | "
                 f"{r['pr']:.3f} | {int(r['outage_days'])} |")
    L += [
        "",
        "## 2024 under the microscope: monthly median PR (unlimited moments)",
        "",
        "| Month | Median PR | Days with PR | Data coverage | Limit loss share |",
        "|---|---|---|---|---|",
    ]
    for p, r in mon.iterrows():
        L.append(f"| {p} | {'–' if pd.isna(r['pr']) else f'{r['pr']:.3f}'} | {int(r['days'])} | {r['coverage']:.0%} | "
                 f"{'–' if pd.isna(r['limit_share']) else f'{r['limit_share']:.0%}'} |")
    L += [
        "",
        "## Events found",
        "",
    ]
    if len(counts):
        L += ["| Year | " + " | ".join(counts.columns) + " |", "|---|" + "---|" * len(counts.columns)]
        for yr, r in counts.iterrows():
            L.append(f"| {yr} | " + " | ".join(str(int(v)) for v in r) + " |")
    L += ["", "Longest of each type:", "", "| Type | Start | End | Days | Value |", "|---|---|---|---|---|"]
    for t in ["outage", "fault", "soiling"]:
        sub = ev[ev["type"] == t].sort_values("days", ascending=False).head(5)
        for _, r in sub.iterrows():
            val = f"{r['value']:,.0f} kWh expected" if t == "outage" else f"{r['value']:.3f}"
            L.append(f"| {t} | {r['start'].date()} | {r['end'].date()} | {r['days']} | {val} |")
    L += [
        "",
        "Value: outage = energy the physics expected during the outage; fault = lowest PR relative to the previous month; "
        "soiling = lowest soiling index.",
        "",
        "## Check against events DKASC reports",
        "",
        "| DKASC note | Period | Data coverage | Twin events overlapping |",
        "|---|---|---|---|",
    ]
    for name, a, b in KNOWN:
        hit, cov = overlap(a, b)
        found = ", ".join(f"{r['type']} {r['start'].date()}–{r['end'].date()}" for _, r in hit.iterrows()) or "none"
        L.append(f"| {name} | {a} to {b} | {cov:.0%} | {found} |")
    L += [
        "",
        "## Rain and dirt",
        "",
        f"- Rain days (ERA5 ≥ {cfg['soiling']['rain_mm_per_day']} mm): {n_rain} in {len(d):,} days.",
        f"- Average change in daily PR from the 3 days before to the 3 days after a rain day: **{rain_change:+.3f}** "
        f"(all days: {all_change:+.3f}). A clear positive jump after rain would point to dirt being washed off.",
        "",
        "## Heat",
        "",
        f"- Panels: on unlimited moments, measured/expected changes by **{slope * 100:+.2f}% per °C** of cell temperature "
        f"(cells mostly {tc_range[0]:.0f}–{tc_range[1]:.0f} °C there). Near zero means the datasheet temperature "
        "coefficient already explains the heat losses. The hottest hours are midday, when the plant is usually held back, "
        "so panel overheating cannot be judged on those hours.",
        f"- Equipment (Temperature_Probe_1/2, inside equipment, not on panels): highest daily maximum "
        f"{d['equipment_temp_max_c'].max():.0f} °C; days with time above {cfg['equipment_heat']['alert_above_c']} °C: "
        f"{int((d['equipment_hot_hours'] > 0).sum())}.",
        "",
    ]
    rep = ROOT / cfg["report_file"]
    rep.write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
