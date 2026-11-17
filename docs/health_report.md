# Plant health report (step 5)

Generated 2026-11-17 12:02 UTC by `scripts/compute_health.py`. Do not edit by hand. Rules and thresholds: `config/twin.yaml` → `health`.

## Where the energy went, by year

Only daylight steps where both the measurement and the physics exist. Health loss = the plant's own condition (ageing, dirt, broken parts). Limit loss = energy the plant could have made in its condition but did not (output held back).

| Year | Physics allows (MWh) | Measured (MWh) | Health loss | Limit loss | Outage loss | Median daily PR | Outage days |
|---|---|---|---|---|---|---|---|
| 2016 | 1,372 | 655 | -64 (-5%) | 714 (52%) | 40 (3%) | 1.054 | 7 |
| 2017 | 2,005 | 1,052 | -90 (-4%) | 1,031 (51%) | 0 (0%) | 1.054 | 0 |
| 2018 | 2,009 | 978 | -57 (-3%) | 1,037 (52%) | 22 (1%) | 1.034 | 4 |
| 2019 | 2,117 | 1,185 | -50 (-2%) | 955 (45%) | 0 (0%) | 1.034 | 0 |
| 2020 | 1,974 | 1,317 | -24 (-1%) | 689 (35%) | 0 (0%) | 1.039 | 0 |
| 2021 | 2,003 | 1,055 | -87 (-4%) | 1,014 (51%) | 0 (0%) | 1.047 | 0 |
| 2022 | 1,914 | 1,122 | -61 (-3%) | 800 (42%) | 16 (1%) | 1.038 | 3 |
| 2023 | 1,829 | 1,066 | -13 (-1%) | 668 (37%) | 10 (1%) | 1.009 | 2 |
| 2024 | 1,718 | 773 | 112 (7%) | 665 (39%) | 33 (2%) | 0.946 | 6 |
| 2025 | 1,950 | 978 | 25 (1%) | 619 (32%) | 19 (1%) | 0.984 | 3 |
| 2026 | 277 | 214 | -5 (-2%) | 68 (25%) | 0 (0%) | 1.016 | 0 |

## 2024 under the microscope: monthly median PR (unlimited moments)

| Month | Median PR | Days with PR | Data coverage | Limit loss share |
|---|---|---|---|---|
| 2022-07 | 1.012 | 23 | 99% | 42% |
| 2022-08 | 1.040 | 21 | 99% | 45% |
| 2022-09 | 1.086 | 23 | 99% | 47% |
| 2022-10 | 1.052 | 31 | 100% | 54% |
| 2022-11 | 1.027 | 30 | 100% | 38% |
| 2022-12 | 1.046 | 29 | 93% | 33% |
| 2023-01 | 1.012 | 23 | 80% | 20% |
| 2023-02 | 1.008 | 27 | 99% | 27% |
| 2023-03 | 1.066 | 29 | 98% | 22% |
| 2023-04 | 1.051 | 22 | 100% | 35% |
| 2023-05 | 1.019 | 26 | 99% | 42% |
| 2023-06 | 1.017 | 20 | 92% | 34% |
| 2023-07 | 1.003 | 24 | 99% | 48% |
| 2023-08 | 0.993 | 18 | 93% | 46% |
| 2023-09 | 1.037 | 25 | 100% | 47% |
| 2023-10 | 0.977 | 13 | 72% | 35% |
| 2023-11 | 0.958 | 27 | 84% | 42% |
| 2023-12 | 0.958 | 29 | 87% | 37% |
| 2024-01 | 0.956 | 27 | 83% | 38% |
| 2024-02 | 0.966 | 23 | 76% | 24% |
| 2024-03 | 0.990 | 18 | 87% | 19% |
| 2024-04 | 1.060 | 10 | 88% | 27% |
| 2024-05 | 0.942 | 17 | 86% | 52% |
| 2024-06 | 0.946 | 17 | 84% | 39% |
| 2024-07 | 0.905 | 14 | 90% | 39% |
| 2024-08 | 0.960 | 16 | 74% | 56% |
| 2024-09 | 0.944 | 20 | 97% | 50% |
| 2024-10 | 0.952 | 27 | 98% | 38% |
| 2024-11 | 0.903 | 29 | 94% | 46% |
| 2024-12 | 0.938 | 29 | 96% | 39% |
| 2025-01 | 0.960 | 29 | 93% | 36% |
| 2025-02 | 0.947 | 21 | 90% | 35% |
| 2025-03 | 1.001 | 21 | 97% | 20% |
| 2025-04 | 1.008 | 16 | 91% | 51% |
| 2025-05 | 0.966 | 21 | 91% | 58% |
| 2025-06 | 0.962 | 22 | 90% | 54% |
| 2025-07 | 0.958 | 3 | 98% | 10% |
| 2025-08 | – | 0 | 99% | 0% |
| 2025-09 | 1.166 | 11 | 100% | 25% |
| 2025-10 | 1.023 | 23 | 100% | 28% |
| 2025-11 | 0.991 | 30 | 95% | 39% |
| 2025-12 | 1.049 | 30 | 100% | 34% |

## Events found

| Year | fault | outage | soiling |
|---|---|---|---|
| 2016 | 0 | 3 | 3 |
| 2017 | 0 | 0 | 4 |
| 2018 | 0 | 4 | 6 |
| 2019 | 0 | 0 | 3 |
| 2020 | 2 | 0 | 7 |
| 2021 | 0 | 0 | 8 |
| 2022 | 2 | 3 | 5 |
| 2023 | 0 | 1 | 7 |
| 2024 | 1 | 2 | 12 |
| 2025 | 1 | 1 | 4 |
| 2026 | 0 | 0 | 1 |

Longest of each type:

| Type | Start | End | Days | Value |
|---|---|---|---|---|
| outage | 2024-10-03 | 2024-10-07 | 5 | 28,242 kWh expected |
| outage | 2016-10-01 | 2016-10-03 | 3 | 18,960 kWh expected |
| outage | 2025-10-05 | 2025-10-07 | 3 | 18,523 kWh expected |
| outage | 2023-07-11 | 2023-07-12 | 2 | 10,422 kWh expected |
| outage | 2016-07-24 | 2016-07-25 | 2 | 10,549 kWh expected |
| fault | 2020-06-30 | 2020-07-07 | 8 | 0.139 |
| fault | 2022-04-23 | 2022-04-30 | 8 | 0.136 |
| fault | 2024-10-04 | 2024-10-10 | 7 | 0.055 |
| fault | 2020-04-08 | 2020-04-12 | 5 | 0.516 |
| fault | 2025-10-06 | 2025-10-10 | 5 | -0.000 |
| soiling | 2020-09-29 | 2020-11-06 | 39 | 0.801 |
| soiling | 2025-10-16 | 2025-11-23 | 39 | 0.848 |
| soiling | 2025-04-17 | 2025-05-23 | 37 | 0.791 |
| soiling | 2023-09-09 | 2023-10-11 | 33 | 0.713 |
| soiling | 2019-10-11 | 2019-11-11 | 32 | 0.827 |

Value: outage = energy the physics expected during the outage; fault = lowest PR relative to the previous month; soiling = lowest soiling index.

## Check against events DKASC reports

| DKASC note | Period | Data coverage | Twin events overlapping |
|---|---|---|---|
| 30 Jan 2023: Yulara weather and source data had intermittent outages 'over recent months' | 2022-10-01 to 2023-01-30 | 93% | soiling 2022-09-24–2022-10-13, soiling 2022-10-29–2022-11-21, soiling 2023-01-11–2023-01-31 |
| 6-13 Oct 2023: website maintenance, Yulara datasets re-syncing | 2023-07-18 to 2023-10-13 | 97% | soiling 2023-09-09–2023-10-11 |

## Rain and dirt

- Rain days (ERA5 ≥ 1.0 mm): 306 in 3,612 days.
- Average change in daily PR from the 3 days before to the 3 days after a rain day: **-0.004** (all days: -0.002). A clear positive jump after rain would point to dirt being washed off.

## Heat

- Panels: on unlimited moments, measured/expected changes by **-0.12% per °C** of cell temperature (cells mostly 16–46 °C there). Near zero means the datasheet temperature coefficient already explains the heat losses. The hottest hours are midday, when the plant is usually held back, so panel overheating cannot be judged on those hours.
- Equipment (Temperature_Probe_1/2, inside equipment, not on panels): highest daily maximum 120 °C; days with time above 75 °C: 578.
