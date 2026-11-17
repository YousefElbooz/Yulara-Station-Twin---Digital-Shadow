# Quality report: station data after cleaning (step 1)

Generated 2026-11-17 11:00 UTC by `scripts/clean_station_data.py` from `config/data.yaml`. Do not edit by hand.

## Rows and time

| | Value |
|---|---|
| Rows in raw file | 1,018,216 |
| Duplicate timestamps dropped | 0 |
| Range (UTC) | 2016-04-01 14:15:00+00:00 to 2026-02-19 14:25:00+00:00 |
| Rows on the regular 5-min grid | 1,039,971 |
| Steps added as gaps (`flag_gap`) | 21,755 |
| Gaps longer than 7.5 min in the raw file | 719 |
| Biggest gap | 7 days 21:15:00 after 2023-01-06 10:05 UTC |

## Values set to missing, per column

| Column | Sentinel (−9e9) | Out of range (bad sensor) | Missing after cleaning | Missing % |
|---|---|---|---|---|
| `p_ac_kw` | 0 | 0 | 34,426 | 3.31% |
| `ghi_wm2` | 0 | 19,012 | 101,099 | 9.72% |
| `pyrano1_wm2` | 1 | 10,926 | 93,014 | 8.94% |
| `t_air_c` | 3 | 0 | 82,101 | 7.89% |
| `wind_ms` | 3 | 0 | 82,090 | 7.89% |
| `wind_dir_deg` | 3 | 0 | 82,090 | 7.89% |
| `wind_gust_ms` | 1 | 0 | 82,088 | 7.89% |
| `pressure_hpa` | 3 | 7 | 82,097 | 7.89% |
| `t_probe1_c` | 0 | 35 | 82,122 | 7.90% |
| `t_probe2_c` | 0 | 2 | 82,089 | 7.89% |
| `current_a` | 0 | 0 | 34,454 | 3.31% |

## Flags

| Flag | Rows | % of grid |
|---|---|---|
| `flag_gap` | 21,755 | 2.09% |
| `flag_missing_power` | 34,426 | 3.31% |
| `flag_night` | 517,627 | 49.77% |
| `flag_bad_sensor` | 29,952 | 2.88% |
| `flag_stuck_power` | 18,835 | 1.81% |

`flag_stuck_power` covers 3.73% of daytime rows that have power. Most common stuck values (rounded to 10 kW):

| Power (kW) | Rows |
|---|---|
| 50 | 2,482 |
| 310 | 2,352 |
| 40 | 2,134 |
| 10 | 1,457 |
| 320 | 739 |

## Cross-checks

- Energy from positive power: 10,395,853.5 kWh (team EDA report: 10,395,853.5 kWh).
- Max power: 915.97 kW (DC rating 1,058.4 kW).
- Night rows with power above 1 kW: 2,167.
