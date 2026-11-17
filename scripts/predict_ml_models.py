"""
Step 7: run every ML model through its adapter, prove the adapters reproduce the training run,
and compare all models with the calibrated physics on 2025.

Reads   data/raw/..csv, data/era5/era5_hourly_site_utc.csv, models_store/friend_v1/*,
        data/clean/station_5min.parquet, data/clean/physics_5min.parquet, data/clean/weather_model_5min.parquet
Writes  data/clean/ml_predictions_5min.parquet   one column per model, UTC index (2022-10-30 onwards)
        docs/model_comparison_2025.md            generated report

Usage (from the project folder)
  .venv\\Scripts\\python scripts\\predict_ml_models.py
"""
import os

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.models.adapters import load_all  # noqa: E402
from backend.models.features import TARGET, TRAIN_FRAC, VAL_FRAC, engineer, load_power, model_table, to_utc  # noqa: E402

MODEL_DIR = ROOT / "models_store/friend_v1"
NAMES = {"ridge": "Ridge Regression", "random_forest": "Random Forest", "xgboost": "XGBoost", "lightgbm": "LightGBM",
         "pinn_dayahead": "DP-PINN (day-ahead)", "lightgbm_nowcast": "Nowcast LightGBM",
         "pinn_nowcast": "DP-PINN (nowcast)", "stacking": "Stacking Ensemble"}


def rmse(a, b):
    return float(np.sqrt(np.mean((np.asarray(a) - np.asarray(b)) ** 2)))


def scores(y, p):
    e = np.asarray(p) - np.asarray(y)
    r = float(np.sqrt(np.mean(e ** 2)))
    return {"n": int(len(e)), "rmse": r, "mae": float(np.mean(np.abs(e))), "bias": float(np.mean(e)), "nrmse": 100 * r / 1058.4}


def main():
    power = load_power(ROOT / "data/raw/5-Site_DG-PV1-DB-DG-M1A.csv")
    era5 = pd.read_csv(ROOT / "data/era5/era5_hourly_site_utc.csv", parse_dates=["time"]).set_index("time")
    df = engineer(power, era5)
    median = pd.Series(json.loads((MODEL_DIR / "train_median.json").read_text()))
    m, fc, fnc = model_table(df, median)
    del df
    n = len(m)
    train_end, val_end = int(n * TRAIN_FRAC), int(n * VAL_FRAC)
    print(f"model table {n:,} rows (training run: 974,878); val from {m.index[train_end]}, test from {m.index[val_end]}")
    summary = json.loads((MODEL_DIR / "run_summary.json").read_text(encoding="utf-8"))
    trained = {r["Model"]: r["RMSE"] for r in summary["results"]}

    A = load_all(MODEL_DIR, fc, fnc)
    y = m[TARGET].values
    rows = np.arange(train_end, n)               # validation + test, every 5-min step
    pred = {}
    for key, ad in A.items():
        if key == "stacking":
            continue
        pred[key] = ad.predict(m, rows)
        print(f"  predicted {key}")
    pred["stacking"] = A["stacking"].predict_from([pred[k] for k in ["random_forest", "xgboost", "lightgbm", "lightgbm_nowcast", "pinn_nowcast"]])

    # ---- check: adapters reproduce the training run's test scores ----
    test = rows >= val_end
    yt = y[rows[test]]
    check = []
    for key in ["ridge", "random_forest", "xgboost", "lightgbm", "lightgbm_nowcast"]:
        check.append((NAMES[key], rmse(yt, pred[key][test]), trained[NAMES[key]]))
    # PINNs were scored on every 2nd window of the test period, as in the notebook
    lb = A["pinn_dayahead"].lookback
    stride2 = np.arange(val_end + lb - 1, n, 2)
    sel = np.searchsorted(rows, stride2)
    for key in ["pinn_dayahead", "pinn_nowcast"]:
        check.append((NAMES[key], rmse(y[stride2], pred[key][sel]), trained[NAMES[key]]))
    # stacking as in the notebook: nowcast PINN predictions on every 2nd window, filled forward
    pn = pd.Series(np.nan, index=np.arange(val_end, n))
    pn.loc[stride2] = pred["pinn_nowcast"][sel]
    pn = pn.ffill().bfill().values
    st_nb = A["stacking"].predict_from([pred["random_forest"][test], pred["xgboost"][test], pred["lightgbm"][test],
                                        pred["lightgbm_nowcast"][test], pn])
    check.append((NAMES["stacking"], rmse(yt, st_nb), trained[NAMES["stacking"]]))

    # ---- save predictions (UTC) ----
    out = pd.DataFrame({f"pred_{k}": v.astype("float32") for k, v in pred.items()}, index=to_utc(m.index[rows]))
    out["persistence_5min"] = m["Power_lag_1"].values[rows].astype("float32")
    out["persistence_24h"] = m["Power_lag_288"].values[rows].astype("float32")
    out["target_kw"] = y[rows].astype("float32")
    out.index.name = "time_utc"
    out.to_parquet(ROOT / "data/clean/ml_predictions_5min.parquet")

    # ---- fair comparison on 2025 (local calendar year) ----
    st = pd.read_parquet(ROOT / "data/clean/station_5min.parquet", columns=["p_ac_kw", "sun_elevation_deg", "flag_stuck_power"])
    wm = pd.read_parquet(ROOT / "data/clean/weather_model_5min.parquet", columns=["src_ghi"])
    ph = pd.read_parquet(ROOT / "data/clean/physics_5min.parquet", columns=["p_expected_cal_kw"])
    j = out.join(st).join(wm).join(ph)
    local_year = (j.index + pd.Timedelta(hours=9.5)).year
    j = j[local_year == 2025]
    j["measured"] = j["p_ac_kw"].clip(lower=0)
    day = (j["sun_elevation_deg"] > 0) & j["measured"].notna() & j["p_expected_cal_kw"].notna()
    unl = (day & (j["sun_elevation_deg"] > 10) & j["p_expected_cal_kw"].between(50, 300) & ~j["flag_stuck_power"]
           & (j["src_ghi"].astype(str) != "era5"))
    rows_cmp = [("persistence_5min", "Persistence: last 5 min", "nowcast"),
                ("persistence_24h", "Persistence: same time yesterday", "day-ahead")]
    rows_cmp += [(f"pred_{k}", NAMES[k], A[k].track) for k in ["ridge", "random_forest", "xgboost", "lightgbm",
                                                                 "pinn_dayahead", "lightgbm_nowcast", "pinn_nowcast", "stacking"]]
    rows_cmp.append(("p_expected_cal_kw", "Calibrated physics (twin)", "physics"))
    res = []
    for col, name, track in rows_cmp:
        a = scores(j.loc[day, "measured"], j.loc[day, col])
        b = scores(j.loc[unl, "measured"], j.loc[unl, col])
        res.append((name, track, a, b))

    L = [
        "# Model comparison (step 7)",
        "",
        f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC by `scripts/predict_ml_models.py`. Do not edit by hand.",
        "",
        "## 1. The adapters reproduce the training run",
        "",
        "Every model was loaded from `models_store/friend_v1/` and run through its adapter (`backend/models/adapters.py`) "
        "with inputs from `backend/models/features.py`. Test RMSE (kW), scored exactly as the notebook does:",
        "",
        "| Model | Through the adapter | Training run | Difference |",
        "|---|---|---|---|",
    ] + [f"| {nm} | {a:.4f} | {b:.4f} | {a - b:+.4f} |" for nm, a, b in check] + [
        "",
        "## 2. All models against the calibrated physics, 2025",
        "",
        "2025 (local calendar year) is after the training run's validation period, so no model saw it. "
        "Two ways of scoring, both against the measured power (kW):",
        "",
        "- **A. All daylight**: how well each one predicts what the plant actually delivered, output limiting included.",
        "- **B. Unlimited moments only**: sun above 10°, physics expects 50–300 kW, no stuck-power flag, station weather "
        "(the moments where the plant is free to follow the sun; same rule as the calibration).",
        "",
        "| Model | Uses | A: RMSE | A: bias | A: nRMSE | B: RMSE | B: bias | B: nRMSE |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name, track, a, b in res:
        L.append(f"| {name} | {track} | {a['rmse']:.1f} | {a['bias']:+.1f} | {a['nrmse']:.2f}% | {b['rmse']:.1f} | {b['bias']:+.1f} | {b['nrmse']:.2f}% |")
    L += [
        "",
        f"Samples: A = {res[0][2]['n']:,} steps, B = {res[0][3]['n']:,} steps. "
        "'nowcast' models use the plant's power from the last hour; 'day-ahead' models do not; the physics uses only the weather.",
        "",
    ]
    keymap = {"persistence_5min": "persistence_5min", "persistence_24h": "persistence_24h", "p_expected_cal_kw": "physics"}
    comp = {}
    for (col, _name, _track), (_n, _t, a, b) in zip(rows_cmp, res):
        comp[keymap.get(col, col.replace("pred_", ""))] = {"all_daylight": a, "unlimited": b}
    (ROOT / "data/clean/model_comparison_2025.json").write_text(json.dumps(comp, indent=1), encoding="utf-8")
    rep = ROOT / "docs/model_comparison_2025.md"
    rep.write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
