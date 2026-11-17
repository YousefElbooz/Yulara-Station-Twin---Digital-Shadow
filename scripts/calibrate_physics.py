"""
Step 4: calibrate the physics model on 2020-2024 and test it on 2025.

What is calibrated: one number, the plant's real DC loss (version 0 assumed 14%).
It is fitted only on moments when the plant is NOT limited: expected power below a ceiling,
sun well up, no stuck-power flag. Step 3 showed that the plant follows the physics there.

Not calibrated (stated in the report): the AC limit (never reached in the data) and the
temperature coefficient (unlimited moments are early/late in the day, when cells are cool).

Reads   data/clean/station_5min.parquet, data/clean/physics_5min.parquet, config/*.yaml
Writes  config/calibration.yaml                      calibration v1
        data/clean/physics_5min.parquet              adds p_expected_cal_kw (calibrated)
        docs/calibration_report.md                   generated report

Usage (from the project folder)
  .venv\\Scripts\\python scripts\\calibrate_physics.py
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
from scripts.simulate_physics import load_weather, model_inputs  # noqa: E402

TRAIN_YEARS = range(2020, 2025)   # agreed split: 2020-2024 train, 2025 test
TEST_YEAR = 2025
UNLIMITED = dict(min_sun_deg=10, min_expected_kw=50, max_expected_kw=300, ratio_trim=(0.5, 1.5))


def load_yaml(name):
    return yaml.safe_load((ROOT / "config" / name).read_text(encoding="utf-8"))


def unlimited_mask(df, expected_col):
    u = UNLIMITED
    return (
        (df["sun_elevation_deg"] > u["min_sun_deg"])
        & df[expected_col].between(u["min_expected_kw"], u["max_expected_kw"])
        & df["p_ac_kw"].notna()
        & ~df["flag_stuck_power"]
        & ~df["flag_gap"]
        & (df["src_ghi"].astype(str) != "era5")   # fit and score only where the station measured the sun
    )


def fit_scale(meas, exp):
    """Least squares through the origin after trimming gross outliers (passing clouds, sensor glitches)."""
    r = meas / exp
    keep = r.between(*UNLIMITED["ratio_trim"])
    m, e = meas[keep], exp[keep]
    return float((m * e).sum() / (e * e).sum()), int(keep.sum()), float(r[keep].median())


def metrics(meas, pred, cap_kw):
    err = pred - meas
    rmse = float(np.sqrt((err ** 2).mean()))
    return {"n": int(len(meas)), "rmse_kw": rmse, "mae_kw": float(err.abs().mean()),
            "mbe_kw": float(err.mean()), "nrmse_pct": 100 * rmse / cap_kw}


def main():
    station, phys = load_yaml("station.yaml"), load_yaml("physics.yaml")
    st = load_weather(phys)
    ph = pd.read_parquet(ROOT / phys["output_file"])
    df = st[["p_ac_kw", "sun_elevation_deg", "flag_stuck_power", "flag_gap", "flag_night", "src_ghi"]].join(ph[["p_expected_kw"]])
    cap = station["array"]["dc_capacity_kw"]
    loss0 = phys["dc_loss_fraction"]

    # ---- fit on 2020-2024 ----
    mask = unlimited_mask(df, "p_expected_kw")
    train = df[mask & df.index.year.isin(TRAIN_YEARS)]
    k, n_fit, med = fit_scale(train["p_ac_kw"], train["p_expected_kw"])
    loss1 = 1 - k * (1 - loss0)

    # ---- the same number year by year (ageing / soiling trend) ----
    yearly = []
    for y in range(2016, 2026):
        sub = df[mask & (df.index.year == y)]
        if len(sub) > 500:
            ky, ny, _ = fit_scale(sub["p_ac_kw"], sub["p_expected_kw"])
            yearly.append((y, ky, 1 - ky * (1 - loss0), ny))

    # ---- calibrated run on all years ----
    calib = {"dc_loss_fraction": float(loss1)}
    parts = []
    for _, chunk in st.groupby(st.index.year):
        parts.append(simulate(model_inputs(chunk), station, phys, calibration=calib)["p_expected_kw"])
    ph["p_expected_cal_kw"] = pd.concat(parts).astype("float32")
    ph.to_parquet(ROOT / phys["output_file"])
    df["p_expected_cal_kw"] = ph["p_expected_cal_kw"]

    # ---- test on 2025 ----
    test = df[df.index.year == TEST_YEAR]
    tm = unlimited_mask(test, "p_expected_cal_kw")
    day = ~test["flag_night"] & test["p_ac_kw"].notna() & test["p_expected_cal_kw"].notna()
    filled = unlimited_mask(test.assign(src_ghi="station"), "p_expected_cal_kw") & (test["src_ghi"].astype(str) == "era5")
    res = {
        "unlimited, calibrated": metrics(test.loc[tm, "p_ac_kw"], test.loc[tm, "p_expected_cal_kw"], cap),
        "unlimited, calibrated, ERA5-filled weather": metrics(test.loc[filled, "p_ac_kw"], test.loc[filled, "p_expected_cal_kw"], cap),
        "unlimited, version 0": metrics(test.loc[tm, "p_ac_kw"], test.loc[tm, "p_expected_kw"], cap),
        "all daytime, calibrated": metrics(test.loc[day, "p_ac_kw"], test.loc[day, "p_expected_cal_kw"], cap),
    }
    e25 = test.loc[day, "p_expected_cal_kw"].sum() / 12e3
    m25 = test.loc[day, "p_ac_kw"].clip(lower=0).sum() / 12e3

    # ---- save calibration v1 ----
    cal_doc = {
        "version": "v1",
        "created_utc": f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M}",
        "fitted_on_years": [min(TRAIN_YEARS), max(TRAIN_YEARS)],
        "method": "least squares through origin of measured vs expected power, unlimited moments only",
        "unlimited_moments": UNLIMITED,
        "samples": n_fit,
        "scale_vs_version0": round(k, 4),
        "dc_loss_fraction": round(float(loss1), 4),
        "not_calibrated": {
            "ac_limit_kw": "never reached in the data (max 916 kW); kept at the calculated 1050 kW",
            "gamma_pdc_per_c": "unlimited moments are early/late in the day with cool cells; kept at datasheet -0.0040",
        },
        "test_year": TEST_YEAR,
        "test_unlimited_rmse_kw": round(res["unlimited, calibrated"]["rmse_kw"], 2),
    }
    (ROOT / "config" / "calibration.yaml").write_text(
        "# Calibration of the physics model. Generated by scripts/calibrate_physics.py; do not edit by hand.\n"
        + yaml.safe_dump(cal_doc, sort_keys=False, allow_unicode=True), encoding="utf-8")

    # ---- report ----
    L = [
        "# Calibration report (step 4, calibration v1)",
        "",
        f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC by `scripts/calibrate_physics.py`. Do not edit by hand.",
        "",
        "## What was fitted",
        "",
        f"- Moments used: sun above {UNLIMITED['min_sun_deg']} deg, expected power {UNLIMITED['min_expected_kw']}–"
        f"{UNLIMITED['max_expected_kw']} kW, no stuck-power flag, no gap; measured/expected trimmed to "
        f"{UNLIMITED['ratio_trim'][0]}–{UNLIMITED['ratio_trim'][1]}.",
        f"- Training years {min(TRAIN_YEARS)}–{max(TRAIN_YEARS)}: {n_fit:,} five-minute samples.",
        f"- Scale versus version 0: **{k:.4f}** (median ratio {med:.4f}).",
        f"- DC loss: version 0 assumed {100 * loss0:.1f}%; calibrated **{100 * loss1:.1f}%**.",
        "- Not calibrated: AC limit (never reached; max measured 916 kW) and temperature coefficient "
        "(the unlimited moments have cool cells). Both stay at their datasheet / calculated values.",
        "",
        "## Same fit, year by year (2016–2025)",
        "",
        "A falling scale means the plant converts less of the same sunlight: ageing, dirt, or failed parts.",
        "",
        "| Year | Scale vs v0 | Implied DC loss | Samples |",
        "|---|---|---|---|",
    ]
    for y, ky, ly, ny in yearly:
        L.append(f"| {y} | {ky:.3f} | {100 * ly:.1f}% | {ny:,} |")
    if len(yearly) > 2:
        ys = np.array([y for y, *_ in yearly], float)
        ks = np.array([kk for _, kk, *_ in yearly])
        slope = np.polyfit(ys, ks, 1)[0]
        L += ["", f"Linear trend of the scale: {100 * slope / ks.mean():+.2f}% per year "
                  f"(crystalline silicon typically loses about 0.5–0.8% per year)."]
    L += [
        "",
        f"## Test on {TEST_YEAR} (not used for fitting)",
        "",
        "| Evaluation | Samples | RMSE kW | MAE kW | Bias kW | nRMSE (of 1,058.4 kW) |",
        "|---|---|---|---|---|---|",
    ]
    for name, r in res.items():
        L.append(f"| {name} | {r['n']:,} | {r['rmse_kw']:.1f} | {r['mae_kw']:.1f} | {r['mbe_kw']:+.1f} | {r['nrmse_pct']:.2f}% |")
    L += [
        "",
        f"{TEST_YEAR} daytime energy: measured {m25:,.0f} MWh, calibrated physics {e25:,.0f} MWh "
        f"(measured = {100 * m25 / e25:.0f}% of what the sunlight allowed).",
        "",
        "Reading the table: the first row is the accuracy of the physics. The last row is large on purpose: "
        "it includes the midday hours when the plant is held back, which the physics does not and should not predict.",
        "",
    ]
    (ROOT / "docs" / "calibration_report.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
