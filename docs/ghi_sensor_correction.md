# GHI sensor correction (step 1b)

Generated 2026-11-17 11:35 UTC by `scripts/correct_ghi_sensor.py`. Do not edit by hand.

**Method in use: `constant`.** Correction applies from **2024-04-01** to the end of the data. Background and decision record: `docs/notes_sensor_and_fixes.md`.

Hours compared: station hourly mean GHI vs ERA5 GHI at the site, ERA5 above 200 W/m².

## Station / ERA5 before the change, by calendar month

| Month | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Ratio | 1.001 | 1.015 | 0.997 | 0.999 | 1.008 | 1.051 | 1.081 | 1.070 | 1.015 | 0.999 | 0.977 | 0.991 |

All-year ratio before the change: 1.012. Normal month-to-month scatter around the calendar-month value: ±0.025 (one standard deviation).

## The jump after the change (ratio ÷ same calendar month before)

| Month | Station / ERA5 | Expected (same month before) | Jump | Factor applied |
|---|---|---|---|---|
| 2024-04 | 1.169 | 0.999 | 1.170 | 0.875 |
| 2024-05 | 1.187 | 1.008 | 1.177 | 0.875 |
| 2024-06 | 1.174 | 1.051 | 1.117 | 0.875 |
| 2024-07 | 1.261 | 1.081 | 1.166 | 0.875 |
| 2024-08 | 1.209 | 1.070 | 1.130 | 0.875 |
| 2024-09 | 1.174 | 1.015 | 1.156 | 0.875 |
| 2024-10 | 1.122 | 0.999 | 1.122 | 0.875 |
| 2024-11 | 1.067 | 0.977 | 1.091 | 0.875 |
| 2024-12 | 1.118 | 0.991 | 1.128 | 0.875 |
| 2025-01 | 1.119 | 1.001 | 1.118 | 0.875 |
| 2025-02 | 1.123 | 1.015 | 1.107 | 0.875 |
| 2025-03 | 1.065 | 0.997 | 1.068 | 0.875 |
| 2025-04 | 1.174 | 0.999 | 1.176 | 0.875 |
| 2025-05 | 1.183 | 1.008 | 1.174 | 0.875 |
| 2025-06 | 1.224 | 1.051 | 1.164 | 0.875 |
| 2025-07 | 1.254 | 1.081 | 1.160 | 0.875 |
| 2025-09 | 1.179 | 1.015 | 1.161 | 0.875 |
| 2025-10 | 1.111 | 0.999 | 1.112 | 0.875 |
| 2025-11 | 1.133 | 0.977 | 1.159 | 0.875 |
| 2025-12 | 1.170 | 0.991 | 1.181 | 0.875 |
| 2026-01 | 1.152 | 1.001 | 1.151 | 0.875 |
| 2026-02 | 1.139 | 1.015 | 1.123 | 0.875 |

Overall jump: **1.143** (2024: 1.140, 2025 onwards: 1.142; scatter ±0.031). Months with no sensor data get factor 0.875.

For comparison, the first method (`monthly`) left June–August corrected GHI at 0.949 of its expected level, i.e. about 5% too low.

Limits: assumes ERA5 itself did not change at the site and that the sensor error is a steady scale factor. Pyranometer_1 (plane of array) shows no jump in April 2024, which points to the GHI sensor.
