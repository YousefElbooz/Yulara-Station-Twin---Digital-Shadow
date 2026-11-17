"""
The ML team's input pipeline, as a reusable function (same code as scripts/train_friend_models.py,
which is a faithful port of their notebook). Every model adapter gets its inputs from here, so the
twin feeds the models exactly what they were trained on.

Time handling, as in the notebook: the table index is LOCAL station time (ACST, tz-naive).
Use to_utc() to line it up with the twin.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

SITE_LAT, SITE_LON, UTC_OFFSET_H = -25.24, 130.99, 9.5
ACCUM_COLS = ["era5_ghi", "era5_ghi_clearsky", "era5_dir_horiz", "era5_precip_mm"]
TARGET = "Power_kW"
TRAIN_FRAC, VAL_FRAC = 0.70, 0.85
NOWCAST_LAGS = ["Power_lag_1", "Power_lag_2", "Power_lag_3", "Power_lag_6", "Power_lag_12"]
PHYS_COLS = ["is_daytime", "GHI_clearsky", "era5_ghi", "cell_temp_estimate", "degradation_factor"]

SOLAR_GEOM = ["solar_elevation_clipped", "cos_solar_zenith", "GHI_clearsky", "is_daytime"]
ERA5_RAD = ["era5_ghi", "era5_ghi_clearsky", "era5_dir_horiz", "era5_diffuse", "era5_diffuse_frac",
            "clearness_index", "GHI_temp_corrected", "cloud_flag"]
ERA5_ATM = ["era5_temp_c", "era5_dewpoint_c", "era5_rh", "era5_wind_speed", "era5_wind_u", "era5_wind_v",
            "era5_pressure_hpa", "era5_tcc", "era5_lcc", "era5_mcc", "era5_hcc", "era5_tcwv",
            "era5_precip_mm", "cell_temp_estimate", "system_age_years", "degradation_factor"]
TIME_CYC = ["hour_sin", "hour_cos", "month_sin", "month_cos", "doy_sin", "doy_cos", "dow_sin", "dow_cos",
            "minute_sin", "minute_cos"]
ERA5_LAGGED = ["era5_ghi_lag_12", "era5_ghi_lag_36", "era5_ghi_lag_72", "era5_ghi_lag_288", "era5_ghi_lag_576",
               "era5_ghi_lag_2016", "era5_tcc_lag_12", "era5_tcc_lag_36", "era5_tcc_lag_288", "Kt_lag_288", "Kt_lag_576"]
INTERACTIONS = ["ghi_x_clearness", "ghi_x_temp", "elevation_x_ghi", "tcc_x_ghi"]


def _lag(s, steps, step_min=5):
    return s.reindex(s.index - pd.Timedelta(minutes=step_min * steps)).values


def engineer(power: pd.Series, era5_hourly: pd.DataFrame) -> pd.DataFrame:
    """power: Power_kW on a local-time 5-min index; era5_hourly: the hourly site CSV (UTC index).
    Returns every column the notebook builds (target included)."""
    df = power.to_frame(TARGET)
    e = era5_hourly.copy()
    e.index = e.index + pd.Timedelta(hours=UTC_OFFSET_H)
    inst, acc = e.drop(columns=ACCUM_COLS), e[ACCUM_COLS].copy()
    acc.index = acc.index - pd.Timedelta(minutes=30)
    tgt = df.index

    def to_grid(g):
        union = g.index.union(tgt)
        return g.reindex(union).interpolate(method="time", limit_area="inside").reindex(tgt)

    era5_5min = pd.concat([to_grid(inst), to_grid(acc)], axis=1)
    for c in ACCUM_COLS:
        era5_5min[c] = era5_5min[c].clip(lower=0)
    df = df.join(era5_5min).dropna(subset=["era5_ghi"])

    idx = df.index
    doy = idx.dayofyear.values.astype(float)
    hour_local = idx.hour.values + idx.minute.values / 60.0
    lat_r = math.radians(SITE_LAT)
    B_v = np.radians((360 / 365) * (doy - 81))
    EoT_v = 9.87 * np.sin(2 * B_v) - 7.53 * np.cos(B_v) - 1.5 * np.sin(B_v)
    solar_time_v = hour_local + (SITE_LON - 15 * UTC_OFFSET_H) / 15 + EoT_v / 60
    H_v = np.radians(15 * (solar_time_v - 12))
    decl_v = np.radians(23.45 * np.sin(np.radians((360 / 365) * (doy - 81))))
    elev_v = np.degrees(np.arcsin(np.clip(np.sin(lat_r) * np.sin(decl_v) + np.cos(lat_r) * np.cos(decl_v) * np.cos(H_v), -1, 1)))
    df["solar_elevation"] = elev_v
    df["solar_elevation_clipped"] = np.clip(elev_v, 0, None)
    df["cos_solar_zenith"] = np.cos(np.radians(90 - elev_v)).clip(0)
    df["day_of_year"] = doy
    df["is_daytime"] = (elev_v > 0).astype(int)
    elev_r = np.radians(np.clip(elev_v, 0.1, 90))
    ghi_cs = 1098 * np.sin(elev_r) * np.exp(-0.057 / np.sin(elev_r))
    ghi_cs[elev_v <= 0] = 0
    df["GHI_clearsky"] = np.clip(ghi_cs, 0, None)
    df["clearness_index"] = (df["era5_ghi"] / df["era5_ghi_clearsky"].where(df["era5_ghi_clearsky"] > 20)).clip(0, 1.3)
    df["cell_temp_estimate"] = df["era5_temp_c"] + ((45 - 20) / 800) * df["era5_ghi"].fillna(0)
    df["GHI_temp_corrected"] = (df["era5_ghi"] * (1 + -0.004 * (df["cell_temp_estimate"] - 25.0))).clip(0)

    df["hour_sin"] = np.sin(2 * np.pi * idx.hour / 24)
    df["hour_cos"] = np.cos(2 * np.pi * idx.hour / 24)
    df["month_sin"] = np.sin(2 * np.pi * idx.month / 12)
    df["month_cos"] = np.cos(2 * np.pi * idx.month / 12)
    df["dow_sin"] = np.sin(2 * np.pi * idx.dayofweek / 7)
    df["dow_cos"] = np.cos(2 * np.pi * idx.dayofweek / 7)
    df["doy_sin"] = np.sin(2 * np.pi * df["day_of_year"] / 365)
    df["doy_cos"] = np.cos(2 * np.pi * df["day_of_year"] / 365)
    df["minute_sin"] = np.sin(2 * np.pi * idx.minute / 60)
    df["minute_cos"] = np.cos(2 * np.pi * idx.minute / 60)
    df["system_age_years"] = (idx - pd.Timestamp("2016-04-01")).total_seconds() / (365.25 * 86400)
    df["degradation_factor"] = (1 - 0.005 * df["system_age_years"]).clip(0.90, 1.0)

    for lab, w in {"1h": "60min", "3h": "180min", "6h": "360min", "12h": "720min", "24h": "1440min"}.items():
        df[f"era5_ghi_roll_mean_{lab}"] = df["era5_ghi"].rolling(w, min_periods=1).mean()
        df[f"era5_ghi_roll_std_{lab}"] = df["era5_ghi"].rolling(w, min_periods=2).std().fillna(0)
    df["era5_kt_roll_mean_3h"] = df["clearness_index"].rolling("180min", min_periods=1).mean()
    df["era5_kt_roll_mean_6h"] = df["clearness_index"].rolling("360min", min_periods=1).mean()
    df["era5_kt_roll_mean_24h"] = df["clearness_index"].rolling("1440min", min_periods=1).mean()
    df["era5_tcc_roll_mean_3h"] = df["era5_tcc"].rolling("180min", min_periods=1).mean()
    df["era5_tcc_roll_mean_6h"] = df["era5_tcc"].rolling("360min", min_periods=1).mean()
    df["era5_tcc_roll_mean_24h"] = df["era5_tcc"].rolling("1440min", min_periods=1).mean()
    df["era5_temp_roll_mean_3h"] = df["era5_temp_c"].rolling("180min", min_periods=1).mean()
    df["era5_diffuse"] = (df["era5_ghi"] - df["era5_dir_horiz"]).clip(lower=0)
    df["era5_diffuse_frac"] = (df["era5_diffuse"] / df["era5_ghi"].where(df["era5_ghi"] > 20)).clip(0, 1)
    df["cloud_flag"] = (df["clearness_index"] < 0.6).astype(float)
    df["ghi_x_clearness"] = df["era5_ghi"] * df["clearness_index"]
    df["ghi_x_temp"] = df["era5_ghi"] * df["era5_temp_c"]
    df["elevation_x_ghi"] = df["solar_elevation_clipped"] * df["era5_ghi"]
    df["tcc_x_ghi"] = df["era5_tcc"] * df["era5_ghi"]

    for lag in [1, 2, 3, 6, 12, 288]:
        df[f"Power_lag_{lag}"] = _lag(df[TARGET], lag)
    for lag in [12, 36, 72, 288, 576, 2016]:
        df[f"era5_ghi_lag_{lag}"] = _lag(df["era5_ghi"], lag)
        df[f"era5_tcc_lag_{lag}"] = _lag(df["era5_tcc"], lag)
    df["Kt_lag_288"] = _lag(df["clearness_index"], 288)
    df["Kt_lag_576"] = _lag(df["clearness_index"], 576)
    return df


def feature_cols(df: pd.DataFrame) -> list[str]:
    roll = sorted(set(c for c in df.columns if c.startswith("era5_") and "_roll_" in c))
    cols = SOLAR_GEOM + ERA5_RAD + ERA5_ATM + roll + TIME_CYC + ERA5_LAGGED + INTERACTIONS + ["Power_lag_288"]
    assert len(cols) == 71
    return cols


def load_power(csv_path: Path) -> pd.Series:
    df = pd.read_csv(csv_path, usecols=["timestamp", "Active_Power"], parse_dates=["timestamp"]).sort_values("timestamp")
    df["timestamp"] = df["timestamp"].dt.floor("5min")
    df = df.drop_duplicates("timestamp", keep="last").set_index("timestamp")
    df.loc[df["Active_Power"] < -1000, "Active_Power"] = np.nan
    return df["Active_Power"].clip(lower=0)


def model_table(df: pd.DataFrame, train_median: pd.Series) -> tuple[pd.DataFrame, list[str], list[str]]:
    """The notebook's df_model: rows with target and baseline lags, imputed with the TRAIN medians
    saved at training time; nowcast lags added (imputed with their train medians, recomputed here)."""
    fc = feature_cols(df)
    keep = list(dict.fromkeys(fc + ["Power_lag_1", "Power_lag_288", TARGET]))
    m = df[keep].dropna(subset=[TARGET, "Power_lag_1", "Power_lag_288"])
    m = m.fillna(train_median.reindex(m.columns))
    te = int(len(m) * TRAIN_FRAC)
    for c in ["Power_lag_2", "Power_lag_3", "Power_lag_6", "Power_lag_12"]:
        m[c] = df[c].reindex(m.index).values
        m[c] = m[c].fillna(float(m.iloc[:te][c].median()))
    fnc = list(dict.fromkeys(fc + NOWCAST_LAGS))
    return m, fc, fnc


def to_utc(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    return (index - pd.Timedelta(hours=UTC_OFFSET_H)).tz_localize("UTC")
