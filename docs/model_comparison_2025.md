# Model comparison (step 7)

Generated 2026-11-17 13:28 UTC by `scripts/predict_ml_models.py`. Do not edit by hand.

## 1. The adapters reproduce the training run

Every model was loaded from `models_store/friend_v1/` and run through its adapter (`backend/models/adapters.py`) with inputs from `backend/models/features.py`. Test RMSE (kW), scored exactly as the notebook does:

| Model | Through the adapter | Training run | Difference |
|---|---|---|---|
| Ridge Regression | 71.0337 | 71.0337 | -0.0000 |
| Random Forest | 77.3325 | 77.3325 | +0.0000 |
| XGBoost | 91.0463 | 91.0463 | +0.0000 |
| LightGBM | 75.9446 | 75.9446 | +0.0000 |
| Nowcast LightGBM | 27.3134 | 27.3134 | +0.0000 |
| DP-PINN (day-ahead) | 70.6891 | 70.6891 | +0.0000 |
| DP-PINN (nowcast) | 29.0951 | 29.0951 | +0.0000 |
| Stacking Ensemble | 27.3186 | 27.3186 | +0.0000 |

## 2. All models against the calibrated physics, 2025

2025 (local calendar year) is after the training run's validation period, so no model saw it. Two ways of scoring, both against the measured power (kW):

- **A. All daylight**: how well each one predicts what the plant actually delivered, output limiting included.
- **B. Unlimited moments only**: sun above 10°, physics expects 50–300 kW, no stuck-power flag, station weather (the moments where the plant is free to follow the sun; same rule as the calibration).

| Model | Uses | A: RMSE | A: bias | A: nRMSE | B: RMSE | B: bias | B: nRMSE |
|---|---|---|---|---|---|---|---|
| Persistence: last 5 min | nowcast | 39.3 | +0.0 | 3.71% | 44.2 | +6.5 | 4.18% |
| Persistence: same time yesterday | day-ahead | 105.2 | -0.1 | 9.94% | 125.3 | +40.0 | 11.84% |
| Ridge Regression | day-ahead | 89.9 | +24.9 | 8.50% | 106.8 | +55.2 | 10.09% |
| Random Forest | day-ahead | 97.7 | +26.3 | 9.23% | 83.4 | +40.7 | 7.88% |
| XGBoost | day-ahead | 115.6 | +36.2 | 10.93% | 79.7 | +28.7 | 7.53% |
| LightGBM | day-ahead | 94.4 | +22.6 | 8.92% | 82.6 | +37.6 | 7.80% |
| DP-PINN (day-ahead) | day-ahead | 89.7 | +17.4 | 8.48% | 84.8 | +28.8 | 8.01% |
| Nowcast LightGBM | nowcast | 36.0 | +0.5 | 3.40% | 41.2 | +10.8 | 3.90% |
| DP-PINN (nowcast) | nowcast | 38.2 | -7.5 | 3.61% | 39.6 | -2.1 | 3.74% |
| Stacking Ensemble | nowcast | 36.0 | +0.4 | 3.40% | 41.1 | +10.3 | 3.88% |
| Calibrated physics (twin) | physics | 351.0 | +231.7 | 33.16% | 34.1 | +0.3 | 3.22% |

Samples: A = 47,481 steps, B = 6,365 steps. 'nowcast' models use the plant's power from the last hour; 'day-ahead' models do not; the physics uses only the weather.
