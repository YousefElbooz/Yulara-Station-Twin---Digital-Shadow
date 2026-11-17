"""
Step 1c (fix of 2026-11-17): the weather the physics model actually uses.

For every 5-min step:
  GHI          corrected station GHI (step 1b); if the sensor is offline, ERA5 GHI
  temperature  station air temperature; if offline, ERA5 2 m temperature
  wind         station wind speed; if offline, ERA5 10 m wind speed
ERA5 is first matched to the station's own sensors using the years before the GHI change:
  GHI          x station/ERA5 ratio of the same calendar month
  temperature  + mean (station - ERA5) difference in daylight
  wind         x mean station/ERA5 ratio in daylight (sensor height differs from 10 m)
ERA5 hourly values are interpolated to the middle of each 5-min interval; accumulated GHI is
placed at the centre of its hour first (same idea as the ML team's 'interp' alignment).

Reads   data/clean/station_5min.parquet, data/clean/ghi_corrected_5min.parquet,
        data/era5/era5_hourly_site_utc.csv, config/data.yaml
Writes  data/clean/weather_model_5min.parquet
        ghi_model_wm2, t_air_model_c, wind_model_ms, src_ghi, src_temp, src_wind

Usage (from the project folder)
  .venv\\Scripts\\python scripts\\build_model_weather.py
"""
import os

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]


def era5_at(series, targets):
    """Linear interpolation of an hourly series to arbitrary timestamps."""
    union = series.index.union(targets)
    return series.reindex(union).interpolate(method="time", limit_area="inside").reindex(targets)


def main():
    cfg = yaml.safe_load((ROOT / "config" / "data.yaml").read_text(encoding="utf-8"))
    fb = cfg["weather_fallback"]
    st = pd.read_parquet(ROOT / "data/clean/station_5min.parquet",
                         columns=["ghi_wm2", "t_air_c", "wind_ms", "sun_elevation_deg"])
    corr = pd.read_parquet(ROOT / cfg["ghi_sensor_correction"]["output_file"])
    era5 = pd.read_csv(ROOT / "data/era5/era5_hourly_site_utc.csv", parse_dates=["time"]).set_index("time")
    era5.index = era5.index.tz_localize("UTC")

    mid = st.index - pd.Timedelta(minutes=cfg["interval_minutes"] / 2)   # station stamp = interval end
    ghi_e = era5["era5_ghi"].copy()
    ghi_e.index = ghi_e.index - pd.Timedelta(minutes=30)                  # hour-ending mean -> hour centre
    e = pd.DataFrame({
        "ghi": era5_at(ghi_e, mid).values,
        "temp": era5_at(era5["era5_temp_c"], mid).values,
        "wind": era5_at(era5["era5_wind_speed"], mid).values,
    }, index=st.index)
    e["ghi"] = e["ghi"].clip(lower=0).where(st["sun_elevation_deg"] > 0, 0.0)

    # match ERA5 to the station sensors, using daylight steps before the GHI change
    ref = (st.index <= pd.Timestamp(fb["adjust_until"], tz="UTC")) & (st["sun_elevation_deg"] > 5)
    month = st.index.month
    both = ref & st["ghi_wm2"].notna() & (e["ghi"] > 0)
    g = pd.DataFrame({"st": st["ghi_wm2"], "e": e["ghi"], "m": month})[both]
    ghi_ratio = g.groupby("m").apply(lambda x: x["st"].sum() / x["e"].sum())
    t_ok = ref & st["t_air_c"].notna() & e["temp"].notna()
    t_offset = float((st["t_air_c"] - e["temp"])[t_ok].mean())
    w_ok = ref & st["wind_ms"].notna() & e["wind"].notna()
    w_ratio = float(st["wind_ms"][w_ok].mean() / e["wind"][w_ok].mean())

    e_ghi = e["ghi"] * month.map(ghi_ratio).values
    e_temp = e["temp"] + t_offset
    e_wind = e["wind"] * w_ratio

    on = fb.get("enabled", True)
    ghi_st = corr["ghi_corr_wm2"]
    out = pd.DataFrame(index=st.index)
    use_e = on & ghi_st.isna() & e_ghi.notna()
    out["ghi_model_wm2"] = ghi_st.where(~use_e, e_ghi).astype("float32")
    out["src_ghi"] = np.where(use_e, "era5", np.where(corr["flag_ghi_corrected"], "station_corrected", "station"))
    use_e = on & st["t_air_c"].isna() & e_temp.notna()
    out["t_air_model_c"] = st["t_air_c"].where(~use_e, e_temp).astype("float32")
    out["src_temp"] = np.where(use_e, "era5", "station")
    use_e = on & st["wind_ms"].isna() & e_wind.notna()
    out["wind_model_ms"] = st["wind_ms"].where(~use_e, e_wind).astype("float32")
    out["src_wind"] = np.where(use_e, "era5", "station")
    for c in ["src_ghi", "src_temp", "src_wind"]:
        out[c] = out[c].astype("category")
    out.to_parquet(ROOT / fb["output_file"])

    day = st["sun_elevation_deg"] > 0
    print("ERA5 -> station adjustment (from daylight before", fb["adjust_until"], "):")
    print("  GHI ratio by month:", {int(k): round(float(v), 3) for k, v in ghi_ratio.items()})
    print(f"  temperature offset: {t_offset:+.2f} C   wind ratio: {w_ratio:.3f}")
    for c in ["src_ghi", "src_temp", "src_wind"]:
        print(f"  {c} in daylight:", out.loc[day, c].value_counts().to_dict())
    print("  daylight steps still without GHI:", int(out.loc[day, "ghi_model_wm2"].isna().sum()))


if __name__ == "__main__":
    main()
