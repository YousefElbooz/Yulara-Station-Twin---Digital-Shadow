"""
Reproduce the ML team's models locally (step 7 preparation).

A faithful port of PV_Forecasting_Analysis_Suite_ERA5.ipynb (USIF-Andreas226/GP, commit 2e63510),
cells 1b, 1c, 3a, 3b, 4a, 4b, 5b, 7a, 8a, 9a-9h, 9j, 11a, 11b. Same data, same features, same split,
same hyper-parameters and seeds. Left out on purpose: plots, ACF/PACF, ADF/KPSS, seasonal
decomposition, Spearman/MI ranking (they print information but do not change any model).
Differences from the notebook (also written to the run summary):
  - inputs come from this project: data/raw/5-Site_DG-PV1-DB-DG-M1A.csv and
    data/era5/era5_hourly_site_utc.csv (downloaded with the notebook's own settings)
  - the day-ahead PINN scaler is saved too (the notebook saved only the nowcast one)
  - the nowcast PINN file stores the correct feature count (the notebook stored 71 instead of 76)
Progress and timings are written to data/training/progress.json for the training tab
(tools/training_monitor).

Usage (from the project folder)
  .venv\\Scripts\\python scripts\\train_friend_models.py
"""
import os

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import gc
import json
import math
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "data/raw/5-Site_DG-PV1-DB-DG-M1A.csv"
ERA5_CSV = ROOT / "data/era5/era5_hourly_site_utc.csv"
OUT_DIR = ROOT / "models_store/friend_v1"
PROGRESS = ROOT / "data/training/progress.json"

SITE_LAT, SITE_LON, SITE_ALT, UTC_OFFSET_H = -25.24, 130.99, 510, 9.5
SEED = 42
ACCUM_COLS = ["era5_ghi", "era5_ghi_clearsky", "era5_dir_horiz", "era5_precip_mm"]

# His test-set results, from the notebook's saved output (cell 12 summary)
FRIEND_RESULTS = {
    "Persistence (lag-1)": 29.4910, "Persistence (same-time yesterday)": 79.4286,
    "Climatology (hour×month mean)": 88.3976, "Ridge Regression": 71.0337, "Random Forest": 77.3325,
    "XGBoost": 94.2701, "LightGBM": 76.2529, "DP-PINN (day-ahead)": 72.4916, "DP-PINN (nowcast)": 29.0214,
    "Nowcast LightGBM": 27.3076, "Stacking Ensemble": 27.3148,
}

STAGES = [
    ("load", "Load target + ERA5"), ("features", "Feature engineering"), ("split", "Train/val/test split"),
    ("baselines", "Persistence + climatology"), ("ridge", "Ridge regression"), ("random_forest", "Random forest"),
    ("xgboost", "XGBoost"), ("lightgbm", "LightGBM"), ("stacking", "Stacking ensemble"),
    ("clustering", "KMeans weather types"), ("pinn_dayahead", "DP-PINN day-ahead (CNN-LSTM)"),
    ("pinn_nowcast", "DP-PINN nowcast (CNN-LSTM)"), ("lgbm_nowcast", "Nowcast LightGBM"),
    ("stacking_refresh", "Stacking (refreshed)"), ("save", "Save models"),
]


class Progress:
    """Writes the run's state to a JSON file the training tab polls."""

    def __init__(self, path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.t0 = time.time()
        self.state = {
            "run_started_utc": datetime.now(timezone.utc).isoformat(),
            "status": "running", "current": None, "updated_utc": None,
            "stages": [{"key": k, "name": n, "status": "pending", "started": None, "ended": None,
                        "seconds": None, "done": None, "total": None, "unit": None, "detail": None, "metrics": None}
                       for k, n in STAGES],
            "results": [], "friend_results": FRIEND_RESULTS, "notes": [],
        }
        self._last_write = 0.0
        self._write(force=True)

    def _stage(self, key):
        return next(s for s in self.state["stages"] if s["key"] == key)

    def start(self, key, total=None, unit=None, detail=None):
        s = self._stage(key)
        s.update(status="running", started=time.time(), total=total, unit=unit, done=0 if total else None,
                 detail=detail)
        self.state["current"] = key
        self._write(force=True)

    def update(self, key, done=None, total=None, detail=None):
        s = self._stage(key)
        if done is not None:
            s["done"] = done
        if total is not None:
            s["total"] = total
        if detail is not None:
            s["detail"] = detail
        self._write()

    def end(self, key, metrics=None, detail=None):
        s = self._stage(key)
        s.update(status="done", ended=time.time(), seconds=round(time.time() - s["started"], 1))
        if s["total"]:
            s["done"] = s["total"]
        if metrics is not None:
            s["metrics"] = metrics
        if detail is not None:
            s["detail"] = detail
        self._write(force=True)

    def result(self, row):
        self.state["results"].append({k: (round(v, 4) if isinstance(v, float) else v) for k, v in row.items()})
        self._write(force=True)

    def note(self, text):
        self.state["notes"].append(text)

    def finish(self, status="done"):
        self.state["status"] = status
        self.state["current"] = None
        self.state["total_seconds"] = round(time.time() - self.t0, 1)
        self._write(force=True)

    def _write(self, force=False):
        now = time.time()
        if not force and now - self._last_write < 1.0:
            return
        self._last_write = now
        self.state["updated_utc"] = datetime.now(timezone.utc).isoformat()
        self.state["elapsed_seconds"] = round(now - self.t0, 1)
        payload = json.dumps(self.state, default=str)
        tmp = self.path.with_suffix(".tmp")
        for attempt in range(5):
            try:
                tmp.write_text(payload, encoding="utf-8")
                os.replace(tmp, self.path)
                return
            except PermissionError:
                time.sleep(0.05 * (attempt + 1))
        try:
            self.path.write_text(payload, encoding="utf-8")
        except PermissionError:
            pass


def evaluate(name, y_true, y_pred, installed_capacity=None):
    from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
    mae = mean_absolute_error(y_true, y_pred)
    rmse = np.sqrt(mean_squared_error(y_true, y_pred))
    mbe = np.mean(y_pred - y_true)
    r2 = r2_score(y_true, y_pred)
    cap = installed_capacity or y_true.max()
    mask = y_true > 1.0
    mape = np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100 if mask.sum() > 0 else np.nan
    return {"Model": name, "MAE": float(mae), "RMSE": float(rmse), "nRMSE%": float(rmse / cap * 100),
            "nMAE%": float(mae / cap * 100), "MBE": float(mbe), "MAPE%": float(mape), "R²": float(r2)}


def main():
    P = Progress(PROGRESS)
    try:
        run(P)
        P.finish("done")
    except Exception as ex:  # noqa: BLE001 - surface any failure in the tab
        P.note(f"FAILED: {type(ex).__name__}: {ex}")
        P.finish("failed")
        raise


def run(P):
    import joblib
    import lightgbm as lgb
    import xgboost as xgb
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.linear_model import Ridge, RidgeCV
    from sklearn.metrics import mean_squared_error
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    np.random.seed(SEED)

    # ---------------- 1b + 1c: target + ERA5 ----------------
    P.start("load")
    df = pd.read_csv(CSV_PATH, usecols=["timestamp", "Active_Power"], parse_dates=["timestamp"])
    df = df.sort_values("timestamp")
    df["timestamp"] = df["timestamp"].dt.floor("5min")
    df = df.drop_duplicates("timestamp", keep="last").set_index("timestamp")
    df.loc[df["Active_Power"] < -1000, "Active_Power"] = np.nan
    df["Power_kW"] = df["Active_Power"].clip(lower=0)
    df = df[["Power_kW"]]

    era5_hourly = pd.read_csv(ERA5_CSV, parse_dates=["time"]).set_index("time")
    e = era5_hourly.copy()
    e.index = e.index + pd.Timedelta(hours=UTC_OFFSET_H)
    inst, acc = e.drop(columns=ACCUM_COLS), e[ACCUM_COLS].copy()
    tgt = df.index
    acc.index = acc.index - pd.Timedelta(minutes=30)

    def to_grid(g):
        union = g.index.union(tgt)
        return g.reindex(union).interpolate(method="time", limit_area="inside").reindex(tgt)

    era5_5min = pd.concat([to_grid(inst), to_grid(acc)], axis=1)
    for c in ACCUM_COLS:
        era5_5min[c] = era5_5min[c].clip(lower=0)
    df = df.join(era5_5min)
    df = df.dropna(subset=["era5_ghi"])
    del era5_5min, inst, acc, e
    P.end("load", detail=f"{len(df):,} rows, {df.index.min()} → {df.index.max()} (local)")

    # ---------------- 3a, 3b, 4a, 4b, 5b: features ----------------
    P.start("features")
    idx = df.index
    doy = idx.dayofyear.values.astype(float)
    hour_local = idx.hour.values + idx.minute.values / 60.0
    lat_r = math.radians(SITE_LAT)
    B_v = np.radians((360 / 365) * (doy - 81))
    EoT_v = 9.87 * np.sin(2 * B_v) - 7.53 * np.cos(B_v) - 1.5 * np.sin(B_v)
    lon_correction = (SITE_LON - 15 * UTC_OFFSET_H) / 15
    solar_time_v = hour_local + lon_correction + EoT_v / 60
    H_v = np.radians(15 * (solar_time_v - 12))
    decl_v = np.radians(23.45 * np.sin(np.radians((360 / 365) * (doy - 81))))
    sin_elev_v = np.sin(lat_r) * np.sin(decl_v) + np.cos(lat_r) * np.cos(decl_v) * np.cos(H_v)
    elev_v = np.degrees(np.arcsin(np.clip(sin_elev_v, -1, 1)))
    df["solar_elevation"] = elev_v
    df["solar_elevation_clipped"] = np.clip(elev_v, 0, None)
    df["cos_solar_zenith"] = np.cos(np.radians(90 - elev_v)).clip(0)
    df["solar_hour_angle"] = 15 * (solar_time_v - 12)
    df["day_of_year"] = doy
    df["is_daytime"] = (elev_v > 0).astype(int)

    elev_r = np.radians(np.clip(df["solar_elevation"].values, 0.1, 90))
    ghi_cs = 1098 * np.sin(elev_r) * np.exp(-0.057 / np.sin(elev_r))
    ghi_cs[df["solar_elevation"].values <= 0] = 0
    df["GHI_clearsky"] = np.clip(ghi_cs, 0, None)
    cs_safe = df["era5_ghi_clearsky"].where(df["era5_ghi_clearsky"] > 20)
    df["clearness_index"] = (df["era5_ghi"] / cs_safe).clip(0, 1.3)
    NOCT = 45
    df["cell_temp_estimate"] = df["era5_temp_c"] + ((NOCT - 20) / 800) * df["era5_ghi"].fillna(0)
    df["GHI_temp_corrected"] = (df["era5_ghi"] * (1 + -0.004 * (df["cell_temp_estimate"] - 25.0))).clip(0)
    P.update("features", detail="solar geometry, clear sky, cell temperature")

    df["hour"] = df.index.hour
    df["month"] = df.index.month
    df["day_of_week"] = df.index.dayofweek
    df["quarter"] = df.index.quarter
    df["year"] = df.index.year
    df["hour_sin"] = np.sin(2 * np.pi * df["hour"] / 24)
    df["hour_cos"] = np.cos(2 * np.pi * df["hour"] / 24)
    df["month_sin"] = np.sin(2 * np.pi * df["month"] / 12)
    df["month_cos"] = np.cos(2 * np.pi * df["month"] / 12)
    df["dow_sin"] = np.sin(2 * np.pi * df["day_of_week"] / 7)
    df["dow_cos"] = np.cos(2 * np.pi * df["day_of_week"] / 7)
    df["doy_sin"] = np.sin(2 * np.pi * df["day_of_year"] / 365)
    df["doy_cos"] = np.cos(2 * np.pi * df["day_of_year"] / 365)
    df["minute_of_hour"] = df.index.minute
    df["minute_sin"] = np.sin(2 * np.pi * df["minute_of_hour"] / 60)
    df["minute_cos"] = np.cos(2 * np.pi * df["minute_of_hour"] / 60)
    INSTALL_DATE = pd.Timestamp("2016-04-01")
    df["system_age_years"] = (df.index - INSTALL_DATE).total_seconds() / (365.25 * 86400)
    df["degradation_factor"] = (1 - 0.005 * df["system_age_years"]).clip(0.90, 1.0)

    ROLL = {"1h": "60min", "3h": "180min", "6h": "360min", "12h": "720min", "24h": "1440min"}
    for lab, w in ROLL.items():
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
    P.update("features", detail="rolling windows and interactions")

    def lag_by_time(s, steps, step_min=5):
        return s.reindex(s.index - pd.Timedelta(minutes=step_min * steps)).values

    for lag in [1, 2, 3, 6, 12, 24, 36, 48, 144, 288, 576, 2016]:
        df[f"Power_lag_{lag}"] = lag_by_time(df["Power_kW"], lag)
    for lag in [12, 36, 72, 288, 576, 2016]:
        df[f"era5_ghi_lag_{lag}"] = lag_by_time(df["era5_ghi"], lag)
        df[f"era5_tcc_lag_{lag}"] = lag_by_time(df["era5_tcc"], lag)
    df["Kt_lag_288"] = lag_by_time(df["clearness_index"], 288)
    df["Kt_lag_576"] = lag_by_time(df["clearness_index"], 576)
    P.end("features", detail=f"{df.shape[1]} columns")

    # ---------------- 7a + 8a: features and split ----------------
    P.start("split")
    SOLAR_GEOM = ["solar_elevation_clipped", "cos_solar_zenith", "GHI_clearsky", "is_daytime"]
    ERA5_RAD = ["era5_ghi", "era5_ghi_clearsky", "era5_dir_horiz", "era5_diffuse", "era5_diffuse_frac",
                "clearness_index", "GHI_temp_corrected", "cloud_flag"]
    ERA5_ATM = ["era5_temp_c", "era5_dewpoint_c", "era5_rh", "era5_wind_speed", "era5_wind_u", "era5_wind_v",
                "era5_pressure_hpa", "era5_tcc", "era5_lcc", "era5_mcc", "era5_hcc", "era5_tcwv",
                "era5_precip_mm", "cell_temp_estimate", "system_age_years", "degradation_factor"]
    ERA5_ROLL = sorted(set(c for c in df.columns if c.startswith("era5_") and "_roll_" in c))
    TIME_CYC = ["hour_sin", "hour_cos", "month_sin", "month_cos", "doy_sin", "doy_cos", "dow_sin", "dow_cos",
                "minute_sin", "minute_cos"]
    ERA5_LAGGED = ["era5_ghi_lag_12", "era5_ghi_lag_36", "era5_ghi_lag_72", "era5_ghi_lag_288", "era5_ghi_lag_576",
                   "era5_ghi_lag_2016", "era5_tcc_lag_12", "era5_tcc_lag_36", "era5_tcc_lag_288",
                   "Kt_lag_288", "Kt_lag_576"]
    INTERACTIONS = ["ghi_x_clearness", "ghi_x_temp", "elevation_x_ghi", "tcc_x_ghi"]
    TARGET = "Power_kW"
    FEATURE_COLS = SOLAR_GEOM + ERA5_RAD + ERA5_ATM + ERA5_ROLL + TIME_CYC + ERA5_LAGGED + INTERACTIONS + ["Power_lag_288"]
    BASELINE_COLS = ["Power_lag_1", "Power_lag_288"]
    FORBIDDEN = {TARGET, "Active_Power", "Active_Energy_Delivered_Received", "Current_Phase_Average_Mean",
                 "ramp_kW", "ramp_kW_per_min"}
    assert not FORBIDDEN & set(FEATURE_COLS)
    assert len(FEATURE_COLS) == 71, len(FEATURE_COLS)

    keep = list(dict.fromkeys(FEATURE_COLS + BASELINE_COLS + [TARGET]))
    df_model = df[keep].dropna(subset=[TARGET] + BASELINE_COLS)
    TRAIN_FRAC, VAL_FRAC = 0.70, 0.85
    n = len(df_model)
    train_end, val_end = int(n * TRAIN_FRAC), int(n * VAL_FRAC)
    train_median = df_model.iloc[:train_end].median(numeric_only=True)
    df_model = df_model.fillna(train_median)

    NOWCAST_LAGS = ["Power_lag_1", "Power_lag_2", "Power_lag_3", "Power_lag_6", "Power_lag_12"]
    extra_lags = df.reindex(df_model.index)[["Power_lag_2", "Power_lag_3", "Power_lag_6", "Power_lag_12"]]
    del df
    gc.collect()

    df_train, df_val, df_test = df_model.iloc[:train_end], df_model.iloc[train_end:val_end], df_model.iloc[val_end:]
    X_train, y_train = df_train[FEATURE_COLS].values, df_train[TARGET].values
    X_val, y_val = df_val[FEATURE_COLS].values, df_val[TARGET].values
    X_test, y_test = df_test[FEATURE_COLS].values, df_test[TARGET].values
    split_info = {k: f"{f.index.min().date()} → {f.index.max().date()} ({len(f):,})"
                  for k, f in [("train", df_train), ("val", df_val), ("test", df_test)]}
    P.end("split", detail=f"{n:,} rows × {len(FEATURE_COLS)} features", metrics=split_info)

    results, val_scores, preds_test = [], {}, {}

    def record(row):
        results.append(row)
        P.result(row)

    # ---------------- 9b, 9c: baselines ----------------
    P.start("baselines")
    yp = df_test["Power_lag_1"].values
    m = ~np.isnan(yp)
    record(evaluate("Persistence (lag-1)", y_test[m], yp[m]))
    yp = df_test["Power_lag_288"].values
    m = ~np.isnan(yp)
    record(evaluate("Persistence (same-time yesterday)", y_test[m], yp[m]))
    climatology = df_train.groupby([df_train.index.hour, df_train.index.month])["Power_kW"].mean()
    keys = pd.MultiIndex.from_arrays([df_test.index.hour, df_test.index.month])
    y_clim = climatology.reindex(keys).fillna(0.0).values
    record(evaluate("Climatology (hour×month mean)", y_test, y_clim))
    P.end("baselines")

    # ---------------- 9d: ridge ----------------
    P.start("ridge")
    ridge = Pipeline([("scaler", StandardScaler()), ("model", Ridge(alpha=10.0))])
    ridge.fit(X_train, y_train)
    y_ridge_val, y_ridge_test = ridge.predict(X_val).clip(0), ridge.predict(X_test).clip(0)
    record(evaluate("Ridge Regression", y_test, y_ridge_test))
    val_scores["Ridge Regression"] = float(np.sqrt(mean_squared_error(y_val, y_ridge_val)))
    P.end("ridge", metrics={"val_rmse": val_scores["Ridge Regression"]})

    # ---------------- 9e: random forest ----------------
    P.start("random_forest", detail="200 trees, depth 12, on 200,000 sampled rows")
    rng = np.random.default_rng(SEED)
    sel = rng.choice(len(X_train), 200_000, replace=False)
    rf = RandomForestRegressor(n_estimators=200, max_depth=12, min_samples_leaf=10, max_features=0.5,
                               n_jobs=-1, random_state=SEED)
    rf.fit(X_train[sel], y_train[sel])
    y_rf_val, y_rf_test = rf.predict(X_val).clip(0), rf.predict(X_test).clip(0)
    record(evaluate("Random Forest", y_test, y_rf_test))
    val_scores["Random Forest"] = float(np.sqrt(mean_squared_error(y_val, y_rf_val)))
    fi_rf = pd.Series(rf.feature_importances_, index=FEATURE_COLS).sort_values(ascending=False)
    P.end("random_forest", metrics={"val_rmse": val_scores["Random Forest"], "top_features": fi_rf.head(5).round(3).to_dict()})

    # ---------------- 9f: xgboost ----------------
    class XgbProgress(xgb.callback.TrainingCallback):
        def after_iteration(self, model, epoch, evals_log):
            P.update("xgboost", done=epoch + 1)
            return False

    P.start("xgboost", total=500, unit="trees")
    xgb_model = xgb.XGBRegressor(n_estimators=500, learning_rate=0.05, max_depth=8, subsample=0.8,
                                 colsample_bytree=0.8, min_child_weight=5, reg_alpha=0.1, reg_lambda=1.0,
                                 tree_method="hist", random_state=SEED, n_jobs=-1, verbosity=0,
                                 callbacks=[XgbProgress()])
    xgb_model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
    xgb_model.set_params(callbacks=None)
    y_xgb_val, y_xgb_test = xgb_model.predict(X_val).clip(0), xgb_model.predict(X_test).clip(0)
    record(evaluate("XGBoost", y_test, y_xgb_test))
    val_scores["XGBoost"] = float(np.sqrt(mean_squared_error(y_val, y_xgb_val)))
    fi_xgb = pd.Series(xgb_model.feature_importances_, index=FEATURE_COLS).sort_values(ascending=False)
    P.end("xgboost", metrics={"val_rmse": val_scores["XGBoost"], "top_features": fi_xgb.head(5).round(3).to_dict()})

    # ---------------- 9g: lightgbm ----------------
    def lgb_progress(key):
        def _cb(env):
            P.update(key, done=env.iteration + 1, total=env.end_iteration)
        return _cb

    P.start("lightgbm", total=500, unit="trees")
    lgbm_model = lgb.LGBMRegressor(n_estimators=500, learning_rate=0.05, num_leaves=63, max_depth=-1,
                                   min_child_samples=20, subsample=0.8, colsample_bytree=0.8, reg_alpha=0.1,
                                   reg_lambda=1.0, random_state=SEED, n_jobs=-1, verbose=-1)
    lgbm_model.fit(X_train, y_train, eval_set=[(X_val, y_val)],
                   callbacks=[lgb.early_stopping(50, verbose=False), lgb_progress("lightgbm")])
    y_lgbm_val, y_lgbm_test = lgbm_model.predict(X_val).clip(0), lgbm_model.predict(X_test).clip(0)
    record(evaluate("LightGBM", y_test, y_lgbm_test))
    val_scores["LightGBM"] = float(np.sqrt(mean_squared_error(y_val, y_lgbm_val)))
    P.end("lightgbm", metrics={"val_rmse": val_scores["LightGBM"], "best_iteration": int(lgbm_model.best_iteration_ or 500)})

    # ---------------- 9h: stacking ----------------
    P.start("stacking")
    meta = RidgeCV(alphas=[0.001, 0.01, 0.1, 1.0, 10.0])
    meta.fit(np.column_stack([y_rf_val, y_xgb_val, y_lgbm_val]), y_val)
    P.end("stacking", metrics={"weights_rf_xgb_lgbm": [round(float(w), 3) for w in meta.coef_]})

    # ---------------- 9j: DP-PINN phase A ----------------
    import torch
    import torch.nn as nn
    from sklearn.cluster import KMeans
    from sklearn.preprocessing import MinMaxScaler
    from torch.utils.data import DataLoader, Dataset

    for c in extra_lags.columns:
        df_model[c] = extra_lags[c].values
    te = int(len(df_model) * TRAIN_FRAC)
    for c in extra_lags.columns:
        df_model[c] = df_model[c].fillna(float(df_model.iloc[:te][c].median()))
    del extra_lags

    PHYS_COLS = ["is_daytime", "GHI_clearsky", "era5_ghi", "cell_temp_estimate", "degradation_factor"]
    CLUSTER_FEATS = ["era5_ghi", "era5_dir_horiz", "era5_diffuse", "era5_rh", "clearness_index", "era5_precip_mm", "era5_tcc"]
    n_total = len(df_model)
    df_train = df_model.iloc[:train_end]
    device = torch.device("cpu")
    torch.manual_seed(SEED)

    LOOKBACK, PINN_BATCH, PINN_LR, MAX_TRAIN_SEQ = 12, 256, 1e-3, 40_000
    VAL_STRIDE, TEST_STRIDE = 4, 2
    G_STC, T_STC, DAY_WEIGHT = 1000.0, 25.0, 4.0
    CAP_KW = float(np.percentile(y_train, 99.5))
    GHI_CS_REF = float(np.percentile(df_train.loc[df_train["is_daytime"] > 0, "GHI_clearsky"], 95))
    STAGES_DA = [(4, "1·Data-heavy"), (5, "2·Physics-up"), (6, "3·Joint")]
    STAGES_NC = [(3, "1·Data-heavy"), (4, "2·Physics-up"), (5, "3·Joint")]

    P.start("clustering")
    _cm = MinMaxScaler()
    Xw_tr = _cm.fit_transform(df_train[CLUSTER_FEATS].fillna(df_train[CLUSTER_FEATS].median()))
    _km = KMeans(n_clusters=4, n_init=10, random_state=SEED)
    _km.fit(Xw_tr)
    _tmp = df_train.copy()
    _tmp["_w"] = _km.predict(Xw_tr)
    _order = _tmp.groupby("_w")["clearness_index"].mean().sort_values(ascending=False).index.tolist()
    _remap = {raw: i for i, raw in enumerate(_order)}
    WEATHER_NAMES = ["Sunny", "Cloudy", "Rainy", "Extreme"]
    Xw = _cm.transform(df_model[CLUSTER_FEATS].fillna(df_train[CLUSTER_FEATS].median()))
    df_model = df_model.copy()
    df_model["weather_type"] = np.array([_remap[int(r)] for r in _km.predict(Xw)], dtype=np.int64)
    df_train, df_val, df_test = df_model.iloc[:train_end], df_model.iloc[train_end:val_end], df_model.iloc[val_end:]
    counts = df_train["weather_type"].map(lambda i: WEATHER_NAMES[i]).value_counts().to_dict()
    del _tmp, Xw, Xw_tr
    P.end("clustering", metrics={"train_counts": counts})

    class AdaptiveLossWeights(nn.Module):
        def __init__(self, init=(0.6, 0.25, 0.15)):
            super().__init__()
            init = np.asarray(init, dtype=np.float64)
            init = init / init.sum()
            self.logits = nn.Parameter(torch.tensor(np.log(init + 1e-8), dtype=torch.float32))

        def forward(self):
            return torch.softmax(self.logits, dim=0)

    class ResidualCNNLSTM(nn.Module):
        def __init__(self, n_feat, cnn_channels=(32, 48), lstm_hidden=64, dropout=0.1, eta0=0.20, alpha0=-0.004):
            super().__init__()
            c1, c2 = cnn_channels
            self.conv = nn.Sequential(nn.Conv1d(n_feat, c1, 3, padding=1), nn.GELU(),
                                      nn.Conv1d(c1, c2, 3, padding=1), nn.GELU(), nn.Dropout(dropout))
            self.lstm = nn.LSTM(c2, lstm_hidden, batch_first=True)
            self.delta_head = nn.Sequential(nn.Linear(lstm_hidden, 32), nn.GELU(), nn.Dropout(dropout), nn.Linear(32, 1))
            self.log_eta = nn.Parameter(torch.tensor(float(np.log(eta0)), dtype=torch.float32))
            self.alpha_raw = nn.Parameter(torch.tensor(float(alpha0), dtype=torch.float32))
            self.cap_kw = float(CAP_KW)

        def get_physical_params(self):
            return torch.exp(self.log_eta).clamp(0.10, 0.35), self.alpha_raw.clamp(-0.008, -0.001)

        def physics_power(self, phys):
            eta, alpha = self.get_physical_params()
            ghi, tcell, degr = phys[:, 2], phys[:, 3], phys[:, 4]
            return (eta * ghi * (1.0 + alpha * (tcell - T_STC)) * degr * (self.cap_kw / G_STC)).clamp(min=0)

        def forward(self, x, base):
            h = self.conv(x.transpose(1, 2)).transpose(1, 2)
            out, _ = self.lstm(h)
            delta = self.delta_head(out[:, -1, :]).squeeze(-1)
            return nn.functional.softplus(base + delta), delta

    class SeqWindowDataset(Dataset):
        def __init__(self, X, y, Phys, base, start, end, lookback, stride=1, max_n=None, rng=None):
            idxs = np.arange(start + lookback - 1, end, stride)
            if max_n is not None and len(idxs) > max_n:
                rng = rng or np.random.RandomState(SEED)
                idxs = np.sort(rng.choice(idxs, max_n, replace=False))
            self.X, self.y, self.Phys, self.base = X, y, Phys, base
            self.idxs, self.lookback = idxs.astype(np.int64), lookback

        def __len__(self):
            return len(self.idxs)

        def __getitem__(self, i):
            t = int(self.idxs[i])
            return (torch.from_numpy(np.ascontiguousarray(self.X[t - self.lookback + 1:t + 1])),
                    torch.tensor(self.y[t], dtype=torch.float32), torch.from_numpy(self.Phys[t].copy()),
                    torch.tensor(self.base[t], dtype=torch.float32))

    def composite_loss(model, y_hat, y, phys, lambdas, day_w=DAY_WEIGHT):
        ld, lp, lc = lambdas[0], lambdas[1], lambdas[2]
        daytime = phys[:, 0]
        w = 1.0 + (day_w - 1.0) * daytime
        Ld = torch.mean(w * (y_hat - y) ** 2)
        L_night = torch.mean((y_hat * (1.0 - daytime)) ** 2)
        p_max = CAP_KW * (phys[:, 1] / (GHI_CS_REF + 1e-3)).clamp(0, 1.2) * phys[:, 4]
        Lp = L_night + torch.mean(torch.relu(y_hat - p_max) ** 2)
        Lc = torch.mean(daytime * (y_hat - model.physics_power(phys)) ** 2)
        total = ld * Ld + lp * Lp + lc * Lc
        eta, alpha = model.get_physical_params()
        return total, {"Ld": float(Ld.detach()), "Lp": float(Lp.detach()), "Lc": float(Lc.detach()),
                       "eta": float(eta.detach()), "alpha": float(alpha.detach()),
                       "ld": float(ld.detach()), "lp": float(lp.detach()), "lc_w": float(lc.detach())}

    @torch.no_grad()
    def predict_loader(model, loader):
        model.eval()
        return np.concatenate([model(xb, bb)[0].numpy() for xb, _, _, bb in loader]).clip(0)

    def align_preds(pred_seq, idxs, split_start, n_split):
        out = np.full(n_split, np.nan, dtype=np.float64)
        out[idxs - split_start] = pred_seq
        return pd.Series(out).ffill().bfill().fillna(0).values, np.isfinite(out)

    def train_residual_model(key, feat_cols, base_all, stages, init_lambda):
        total_epochs = sum(e for e, _ in stages)
        P.start(key, total=total_epochs, unit="epochs")
        scaler = StandardScaler()
        X_all = np.empty((n_total, len(feat_cols)), dtype=np.float32)
        X_all[:train_end] = scaler.fit_transform(df_model.iloc[:train_end][feat_cols].values).astype(np.float32)
        X_all[train_end:] = scaler.transform(df_model.iloc[train_end:][feat_cols].values).astype(np.float32)
        y_all = df_model[TARGET].values.astype(np.float32)
        P_all = df_model[PHYS_COLS].values.astype(np.float32)
        rng = np.random.RandomState(SEED)
        ds_tr = SeqWindowDataset(X_all, y_all, P_all, base_all, 0, train_end, LOOKBACK, stride=3, max_n=MAX_TRAIN_SEQ, rng=rng)
        ds_va = SeqWindowDataset(X_all, y_all, P_all, base_all, train_end, val_end, LOOKBACK, stride=VAL_STRIDE)
        ds_te = SeqWindowDataset(X_all, y_all, P_all, base_all, val_end, n_total, LOOKBACK, stride=TEST_STRIDE)
        idx_va, idx_te = ds_va.idxs.copy(), ds_te.idxs.copy()
        dl_tr = DataLoader(ds_tr, batch_size=PINN_BATCH, shuffle=True, num_workers=0)
        dl_va = DataLoader(ds_va, batch_size=PINN_BATCH * 2, shuffle=False, num_workers=0)
        dl_te = DataLoader(ds_te, batch_size=PINN_BATCH * 2, shuffle=False, num_workers=0)
        model = ResidualCNNLSTM(n_feat=len(feat_cols))
        aw = AdaptiveLossWeights(init_lambda)
        opt = torch.optim.AdamW([{"params": model.parameters(), "lr": PINN_LR},
                                 {"params": aw.parameters(), "lr": PINN_LR * 0.5}], weight_decay=1e-4)
        hist, best_val, best_state, best_aw, gep = [], np.inf, None, None, 0
        n_batches = len(dl_tr)
        for n_ep, label in stages:
            if "Data" in label:
                with torch.no_grad():
                    aw.logits.copy_(torch.tensor(np.log([0.70, 0.20, 0.10])))
            elif "Physics" in label:
                with torch.no_grad():
                    aw.logits.copy_(torch.tensor(np.log([0.50, 0.30, 0.20])))
            opt.param_groups[0]["lr"] = PINN_LR * (0.5 if "Joint" in label else 1.0)
            opt.param_groups[1]["lr"] = PINN_LR * 0.25 if "Joint" in label else PINN_LR * 0.5
            bad = 0
            for _ in range(n_ep):
                gep += 1
                model.train()
                aw.train()
                parts_list = []
                for b, (xb, yb, pb, bb) in enumerate(dl_tr):
                    opt.zero_grad(set_to_none=True)
                    yhat, _ = model(xb, bb)
                    loss, parts = composite_loss(model, yhat, yb, pb, aw())
                    loss.backward()
                    nn.utils.clip_grad_norm_(model.parameters(), 5.0)
                    opt.step()
                    parts_list.append(parts)
                    if b % 20 == 0:
                        P.update(key, done=gep - 1 + b / n_batches,
                                 detail=f"{label} · epoch {gep}/{total_epochs} · batch {b + 1}/{n_batches}")
                yhat_va = predict_loader(model, dl_va)
                rmse = float(np.sqrt(np.mean((yhat_va - y_all[idx_va]) ** 2)))
                tr = {k: float(np.mean([p[k] for p in parts_list])) for k in parts_list[0]}
                hist.append({"epoch": gep, "stage": label, **tr, "val_rmse": rmse})
                P.update(key, done=gep, detail=f"{label} · epoch {gep}/{total_epochs} · val RMSE {rmse:.2f} kW · "
                                               f"η={tr['eta']:.3f} α={tr['alpha']:.4f}")
                if rmse < best_val - 1e-6:
                    best_val, bad = rmse, 0
                    best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
                    best_aw = {k: v.detach().clone() for k, v in aw.state_dict().items()}
                else:
                    bad += 1
                    if bad >= 4 and "Joint" in label:
                        break
        model.load_state_dict(best_state)
        aw.load_state_dict(best_aw)
        yv, yt = predict_loader(model, dl_va), predict_loader(model, dl_te)
        y_val_f, m_val = align_preds(yv, idx_va, train_end, len(y_val))
        y_te_f, m_te = align_preds(yt, idx_te, val_end, len(y_test))
        eta_f, alpha_f = model.get_physical_params()
        P.end(key, metrics={"best_val_rmse": best_val, "eta": float(eta_f), "alpha": float(alpha_f),
                            "epochs_run": gep, "history": hist})
        del X_all, dl_tr, dl_va, dl_te, ds_tr, ds_va, ds_te
        gc.collect()
        return dict(model=model, aw=aw, scaler=scaler, hist=hist, y_val=y_val_f, y_test=y_te_f,
                    m_val=m_val, m_te=m_te, feat_cols=feat_cols, best_val=best_val)

    def stc_base_np(Phys, eta=0.20, alpha=-0.004):
        ghi, tcell, degr = Phys[:, 2], Phys[:, 3], Phys[:, 4]
        return np.clip(eta * ghi * (1.0 + alpha * (tcell - T_STC)) * degr * (CAP_KW / G_STC), 0, None)

    P_all_phys = df_model[PHYS_COLS].values.astype(np.float32)
    base_da = (0.65 * stc_base_np(P_all_phys) + 0.35 * df_model["Power_lag_288"].values.astype(np.float32)).astype(np.float32)
    da = train_residual_model("pinn_dayahead", FEATURE_COLS, base_da, STAGES_DA, (0.55, 0.25, 0.20))
    FEATS_NC = list(dict.fromkeys(FEATURE_COLS + NOWCAST_LAGS))
    base_nc = df_model["Power_lag_1"].values.astype(np.float32)
    nc = train_residual_model("pinn_nowcast", FEATS_NC, base_nc, STAGES_NC, (0.70, 0.20, 0.10))

    P.start("lgbm_nowcast", total=600, unit="trees")
    lgbm_nc = lgb.LGBMRegressor(n_estimators=600, learning_rate=0.05, num_leaves=64, min_child_samples=30,
                                subsample=0.8, colsample_bytree=0.8, reg_alpha=0.1, reg_lambda=1.0,
                                random_state=SEED, n_jobs=2, verbose=-1)
    lgbm_nc.fit(df_train[FEATS_NC].values, df_train[TARGET].values,
                eval_set=[(df_val[FEATS_NC].values, df_val[TARGET].values)],
                callbacks=[lgb.early_stopping(50, verbose=False), lgb_progress("lgbm_nowcast")])
    y_lgbm_nc_val, y_lgbm_nc_test = lgbm_nc.predict(df_val[FEATS_NC].values).clip(0), lgbm_nc.predict(df_test[FEATS_NC].values).clip(0)
    P.end("lgbm_nowcast", metrics={"best_iteration": int(lgbm_nc.best_iteration_ or 600)})

    y_val, y_test = df_val[TARGET].values, df_test[TARGET].values
    record(evaluate("DP-PINN (day-ahead)", y_test[da["m_te"]], da["y_test"][da["m_te"]]))
    val_scores["DP-PINN (day-ahead)"] = float(np.sqrt(mean_squared_error(y_val[da["m_val"]], da["y_val"][da["m_val"]])))
    record(evaluate("DP-PINN (nowcast)", y_test[nc["m_te"]], nc["y_test"][nc["m_te"]]))
    val_scores["DP-PINN (nowcast)"] = float(np.sqrt(mean_squared_error(y_val[nc["m_val"]], nc["y_val"][nc["m_val"]])))
    record(evaluate("Nowcast LightGBM", y_test, y_lgbm_nc_test))
    val_scores["Nowcast LightGBM"] = float(np.sqrt(mean_squared_error(y_val, y_lgbm_nc_val)))

    P.start("stacking_refresh")
    meta = RidgeCV(alphas=[0.001, 0.01, 0.1, 1.0, 10.0])
    meta.fit(np.column_stack([y_rf_val, y_xgb_val, y_lgbm_val, y_lgbm_nc_val, nc["y_val"]]), y_val)
    y_stack_val = meta.predict(np.column_stack([y_rf_val, y_xgb_val, y_lgbm_val, y_lgbm_nc_val, nc["y_val"]])).clip(0)
    y_stack_test = meta.predict(np.column_stack([y_rf_test, y_xgb_test, y_lgbm_test, y_lgbm_nc_test, nc["y_test"]])).clip(0)
    record(evaluate("Stacking Ensemble", y_test, y_stack_test))
    val_scores["Stacking Ensemble"] = float(np.sqrt(mean_squared_error(y_val, y_stack_val)))
    wt = df_test["weather_type"].values
    by_weather = {}
    for i, name in enumerate(WEATHER_NAMES):
        mm = (wt == i) & da["m_te"]
        if mm.sum() >= 50:
            by_weather[name] = float(np.sqrt(mean_squared_error(y_test[mm], da["y_test"][mm])))
    P.end("stacking_refresh", metrics={"weights": [round(float(w), 3) for w in meta.coef_],
                                       "best_on_validation": min(val_scores, key=val_scores.get),
                                       "dayahead_rmse_by_weather": by_weather})

    # ---------------- 11a, 11b: save ----------------
    P.start("save")
    import shutil
    FRIEND_OUT_DIR = Path(r"C:\Users\Yousef\Desktop\College\Friend_GP_Repo\pv_models")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(rf, OUT_DIR / "random_forest.pkl")
    joblib.dump(lgbm_model, OUT_DIR / "lightgbm.pkl")
    joblib.dump(xgb_model, OUT_DIR / "xgboost.pkl")
    joblib.dump(ridge, OUT_DIR / "ridge.pkl")
    joblib.dump(lgbm_nc, OUT_DIR / "lightgbm_nowcast.pkl")
    joblib.dump(nc["scaler"], OUT_DIR / "pinn_x_scaler.pkl")
    joblib.dump(da["scaler"], OUT_DIR / "pinn_dayahead_x_scaler.pkl")
    joblib.dump(meta, OUT_DIR / "stacking_meta.pkl")
    for tag, r in [("dayahead", da), ("nowcast", nc)]:
        eta, alpha = r["model"].get_physical_params()
        torch.save({"state_dict": r["model"].state_dict(), "arch": f"Residual-CNN-LSTM-PINN-{tag}",
                    "n_feat": len(r["feat_cols"]), "feat_cols": r["feat_cols"], "lookback": LOOKBACK,
                    "CAP_KW": CAP_KW, "GHI_CS_REF": GHI_CS_REF, "G_STC": G_STC, "T_STC": T_STC,
                    "eta": float(eta), "alpha": float(alpha)}, OUT_DIR / f"cnn_lstm_pinn_{tag}.pt")
    (OUT_DIR / "feature_cols.txt").write_text("\n".join(FEATURE_COLS), encoding="utf-8")
    (OUT_DIR / "feature_cols_nowcast.txt").write_text("\n".join(FEATS_NC), encoding="utf-8")
    train_median[FEATURE_COLS].to_json(OUT_DIR / "train_median.json")
    summary = {"results": results, "val_scores": val_scores, "split": split_info,
               "source_notebook": "USIF-Andreas226/GP PV_Forecasting_Analysis_Suite_ERA5.ipynb @ 2e63510",
               "created_utc": datetime.now(timezone.utc).isoformat()}
    (OUT_DIR / "run_summary.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
    if FRIEND_OUT_DIR.parent.exists():
        FRIEND_OUT_DIR.mkdir(parents=True, exist_ok=True)
        for item in OUT_DIR.iterdir():
            if item.is_file():
                shutil.copy2(item, FRIEND_OUT_DIR / item.name)
    P.note("Day-ahead PINN scaler saved as pinn_dayahead_x_scaler.pkl (the notebook did not save it).")
    P.note("Nowcast PINN file stores n_feat = 76 (the notebook stored 71).")
    P.note(f"Models saved to {OUT_DIR.relative_to(ROOT)} and mirrored to {FRIEND_OUT_DIR}.")
    P.end("save", detail=f"{OUT_DIR.relative_to(ROOT)} + Friend_GP_Repo/pv_models")


if __name__ == "__main__":
    main()
