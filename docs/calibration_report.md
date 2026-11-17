# Calibration report (step 4, calibration v1)

Generated 2026-11-17 11:36 UTC by `scripts/calibrate_physics.py`. Do not edit by hand.

## What was fitted

- Moments used: sun above 10 deg, expected power 50–300 kW, no stuck-power flag, no gap; measured/expected trimmed to 0.5–1.5.
- Training years 2020–2024: 47,401 five-minute samples.
- Scale versus version 0: **1.0441** (median ratio 1.0672).
- DC loss: version 0 assumed 14.0%; calibrated **10.2%**.
- Not calibrated: AC limit (never reached; max measured 916 kW) and temperature coefficient (the unlimited moments have cool cells). Both stay at their datasheet / calculated values.

## Same fit, year by year (2016–2025)

A falling scale means the plant converts less of the same sunlight: ageing, dirt, or failed parts.

| Year | Scale vs v0 | Implied DC loss | Samples |
|---|---|---|---|
| 2016 | 1.094 | 5.9% | 8,743 |
| 2017 | 1.088 | 6.4% | 10,369 |
| 2018 | 1.058 | 9.0% | 9,217 |
| 2019 | 1.061 | 8.7% | 8,332 |
| 2020 | 1.067 | 8.2% | 10,628 |
| 2021 | 1.071 | 7.9% | 10,067 |
| 2022 | 1.065 | 8.4% | 10,127 |
| 2023 | 1.030 | 11.4% | 8,328 |
| 2024 | 0.968 | 16.8% | 8,251 |
| 2025 | 1.018 | 12.4% | 6,780 |

Linear trend of the scale: -0.95% per year (crystalline silicon typically loses about 0.5–0.8% per year).

## Test on 2025 (not used for fitting)

| Evaluation | Samples | RMSE kW | MAE kW | Bias kW | nRMSE (of 1,058.4 kW) |
|---|---|---|---|---|---|
| unlimited, calibrated | 6,793 | 33.7 | 18.0 | +0.5 | 3.18% |
| unlimited, calibrated, ERA5-filled weather | 2,425 | 67.7 | 44.7 | +5.3 | 6.40% |
| unlimited, version 0 | 6,793 | 33.8 | 18.6 | -7.1 | 3.20% |
| all daytime, calibrated | 50,393 | 350.6 | 241.4 | +231.5 | 33.12% |

2025 daytime energy: measured 978 MWh, calibrated physics 1,950 MWh (measured = 50% of what the sunlight allowed).

Reading the table: the first row is the accuracy of the physics. The last row is large on purpose: it includes the midday hours when the plant is held back, which the physics does not and should not predict.
