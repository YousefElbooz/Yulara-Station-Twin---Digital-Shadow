# Physics model validation (step 3, version 0: not calibrated)

Generated 2026-11-17 11:36 UTC by `scripts/simulate_physics.py`. Do not edit by hand.

Model: decomposition = erbs, transposition = perez, albedo = 0.25, iam = physical, temperature_model = sapm_open_rack_glass_polymer, dc_loss_fraction = 0.14. Station: 1058.4 kW DC, tilt 15 deg, azimuth 0 deg (north), AC limit 1050.0 kW (calculated).

## Clear days

867 clear days out of 3,611 days with data (criteria in `config/physics.yaml`).

## Measured / expected power on clear days, median by local hour

Only steps with expected power above 50 kW. A model that is right and a plant that is free to produce would give a flat line near 1.

| Local hour (ACST) | summer (Dec-Feb) | winter (Jun-Aug) |
|---|---|---|
| 06:00 | 0.59 | – |
| 07:00 | 0.89 | 0.90 |
| 08:00 | 1.03 | 1.06 |
| 09:00 | 0.82 | 0.96 |
| 10:00 | 0.54 | 0.45 |
| 11:00 | 0.46 | 0.22 |
| 12:00 | 0.47 | 0.14 |
| 13:00 | 0.53 | 0.15 |
| 14:00 | 0.65 | 0.21 |
| 15:00 | 0.87 | 0.40 |
| 16:00 | 1.01 | 0.91 |
| 17:00 | 1.07 | 1.07 |
| 18:00 | 1.02 | 1.00 |

## When the plant is far below any limit (expected power under 300 kW, clear days)

- Median measured / expected, morning: **1.043**
- Median measured / expected, afternoon: **1.083**

## Yearly energy, measured vs expected (only steps where both exist)

| Year | Measured MWh | Expected MWh | Measured % | Daylight coverage of the model |
|---|---|---|---|---|
| 2016 | 655 | 1,314 | 50% | 100% |
| 2017 | 1,052 | 1,920 | 55% | 100% |
| 2018 | 979 | 1,924 | 51% | 100% |
| 2019 | 1,185 | 2,027 | 58% | 100% |
| 2020 | 1,317 | 1,890 | 70% | 100% |
| 2021 | 1,055 | 1,918 | 55% | 100% |
| 2022 | 1,122 | 1,832 | 61% | 100% |
| 2023 | 1,067 | 1,751 | 61% | 100% |
| 2024 | 773 | 1,646 | 47% | 100% |
| 2025 | 978 | 1,867 | 52% | 100% |
| 2026 | 214 | 265 | 81% | 100% |

## What does Pyranometer_1 measure? (clear days, within 2 deg of the day's highest sun)

| Month | GHI (station) | Pyranometer_1 | Modelled plane-of-array |
|---|---|---|---|
| 1 | 1109 | 1100 | 1104 |
| 2 | 1064 | 1096 | 1107 |
| 3 | 981 | 1062 | 1077 |
| 4 | 887 | 1000 | 1015 |
| 5 | 757 | 907 | 919 |
| 6 | 687 | 852 | 861 |
| 7 | 711 | 877 | 880 |
| 8 | 808 | 947 | 958 |
| 9 | 941 | 1034 | 1049 |
| 10 | 1062 | 1097 | 1114 |
| 11 | 1108 | 1090 | 1114 |
| 12 | 1113 | 1066 | 1095 |
