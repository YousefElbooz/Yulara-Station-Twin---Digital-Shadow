"""
The twin engine: one call per 5-minute step.

For each step it
  1. takes the plant's measurement and the weather (from a source),
  2. runs the calibrated physics for that moment -> expected power,
  3. compares the two -> a status (night / offline / outage / limited / healthy),
  4. opens or closes alarms (rules in config/twin.yaml -> runtime.alarms),
  5. when a local day ends, closes the day: daily PR, limit loss, fault and soiling rules,
  6. saves everything in the store.
The engine never invents numbers: a step without measurement is 'offline', a step without any
weather has no expected power.
"""
from __future__ import annotations

import math

import pandas as pd

from backend.health.indicators import LOCAL, add_rolling, daily_table
from backend.physics.pv_chain import simulate


def _num(v):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else float(v)


class TwinEngine:
    def __init__(self, station: dict, physics: dict, calibration: dict, twin_cfg: dict, store,
                 day_history: pd.DataFrame, rain_mm: pd.Series, models=None):
        self.station, self.physics, self.cal = station, physics, calibration
        self.rt, self.health = twin_cfg["runtime"], twin_cfg["health"]
        self.store = store
        self.models = models                    # ML forecasts (backend.models.hub), optional
        self.days = day_history.copy()          # closed days before the start (from step 5)
        self.rain = rain_mm
        self.counters = {k: [0, 0] for k in self.rt["alarms"]}   # [steps in condition, steps out of it]
        self.open_ids: dict[str, int] = {}
        self.today: list[dict] = []
        self.current_date = None
        self.last = None
        self.plant_feed = True   # False in live-weather mode: no measured power, so no plant alarms or daily records

    # ------------------------------------------------------------------ one step
    def step(self, t: pd.Timestamp, row: dict | None) -> dict:
        local_date = (t + LOCAL).date()
        if self.current_date is not None and local_date != self.current_date:
            self._close_day()
        self.current_date = local_date

        row = row or {"time_utc": t}
        sun = _num(row.get("sun_elevation_deg"))
        daylight = sun is not None and sun > 0
        measured = _num(row.get("p_ac_kw"))
        ghi, tair, wind = (_num(row.get(k)) for k in ("ghi_model_wm2", "t_air_model_c", "wind_model_ms"))

        expected = poa = tcell = None
        if ghi is not None and tair is not None:
            w = pd.DataFrame({"ghi_wm2": [ghi], "t_air_c": [tair], "wind_ms": [wind if wind is not None else 1.0]},
                             index=pd.DatetimeIndex([t]))
            sim = simulate(w, self.station, self.physics, calibration=self.cal).iloc[0]
            expected, poa, tcell = _num(sim["p_expected_kw"]), _num(sim["poa_global_wm2"]), _num(sim["t_cell_c"])
            if sun is None:
                sun = 90 - float(sim["sun_zenith_deg"])
                daylight = sun > 0

        probes = [v for v in (_num(row.get("t_probe1_c")), _num(row.get("t_probe2_c"))) if v is not None]
        equip = max(probes) if probes else None
        rt = self.rt
        if not daylight:
            status = "night"
        elif measured is None and not self.plant_feed:
            status = "weather_only"
        elif measured is None:
            status = "offline"
        elif expected is not None and expected >= rt["outage_min_expected_kw"] and measured < rt["outage_max_share"] * expected:
            status = "outage"
        elif expected is not None and expected >= rt["limited_min_expected_kw"] and measured < rt["limited_max_share"] * expected:
            status = "limited"
        else:
            status = "healthy"

        src = "era5" if "era5" in (row.get("src_ghi"), row.get("src_temp")) else str(row.get("src_ghi") or "none")
        step = {
            "time_utc": t.isoformat(), "measured_kw": measured, "expected_kw": expected,
            "ratio": (measured / expected) if (measured is not None and expected and expected > 1) else None,
            "status": status, "ghi_wm2": ghi, "poa_wm2": poa, "t_air_c": tair, "t_cell_c": tcell,
            "wind_ms": wind, "wind_dir_deg": _num(row.get("wind_dir_deg")), "equipment_temp_c": equip,
            "sun_elevation_deg": sun, "src_weather": src,
        }
        self.store.add_step(step)
        preds = self.models.get(t) if self.models is not None else {}
        self.store.add_predictions(step["time_utc"], preds)
        step["models"] = preds

        # step alarms; OFFLINE and OUTAGE are judged in daylight only (nights neither open nor close them)
        cond = {
            "OFFLINE": (status == "offline") if (daylight and self.plant_feed) else None,
            # judged only when the physics expects real power, so dawn and dusk do not close it
            "OUTAGE": (status == "outage") if (daylight and expected is not None
                                               and expected >= rt["outage_min_expected_kw"]) else None,
            "WEATHER_SENSORS_OFF": src == "era5",
            "EQUIPMENT_HOT": equip is not None and equip > rt["alarms"]["EQUIPMENT_HOT"]["threshold_c"],
        }
        for name, c in cond.items():
            if c is not None:
                self._update_alarm(name, c, t)

        self.today.append({
            "time": t, "p_ac_kw": measured, "p_expected_cal_kw": expected, "sun_elevation_deg": sun,
            "flag_stuck_power": bool(row.get("flag_stuck_power") or False), "src_ghi": str(row.get("src_ghi")),
            "t_probe1_c": _num(row.get("t_probe1_c")), "t_probe2_c": _num(row.get("t_probe2_c")),
        })
        self.last = step
        self._save_state(t)
        return step

    # ------------------------------------------------------------------ alarms
    def _update_alarm(self, name: str, active: bool, t: pd.Timestamp):
        cfg = self.rt["alarms"][name]
        need = cfg.get("steps", 1)
        c = self.counters[name]
        if active:
            c[0], c[1] = c[0] + 1, 0
        else:
            c[0], c[1] = 0, c[1] + 1
        if active and c[0] >= need and name not in self.open_ids:
            start = t - pd.Timedelta(minutes=5 * (need - 1))
            self.open_ids[name] = self.store.open_alarm({
                "type": name, "severity": cfg["severity"], "confidence": cfg.get("confidence", "normal"),
                "start_utc": start.isoformat(), "message": cfg["message"], "recommendation": cfg["recommendation"]})
        if not active and c[1] >= need and name in self.open_ids:
            self.store.close_alarm(self.open_ids.pop(name), (t - pd.Timedelta(minutes=5 * need)).isoformat())

    # ------------------------------------------------------------------ end of a local day
    def _close_day(self):
        if not self.plant_feed:      # nothing measured: a daily record would be a fake 0 kWh day
            self.today = []
            return
        rows = pd.DataFrame(self.today).set_index("time")
        self.today = []
        if rows.empty:
            return
        for c in ["p_ac_kw", "p_expected_cal_kw", "sun_elevation_deg", "t_probe1_c", "t_probe2_c"]:
            rows[c] = pd.to_numeric(rows[c], errors="coerce")
        d = daily_table(rows, self.rain, self.health)
        base_cols = ["measured_kwh", "expected_kwh", "expected_full_day_kwh", "coverage", "unlimited_samples",
                     "pr_unlimited", "equipment_temp_max_c", "equipment_hot_hours", "rain_mm"]
        self.days = pd.concat([self.days[~self.days.index.isin(d.index)], d[base_cols]]).sort_index()
        self.days = add_rolling(self.days[base_cols], self.health)
        last = self.days.iloc[-1]
        day_t = pd.Timestamp(self.days.index[-1])
        self.store.add_day({
            "date": str(day_t.date()), "measured_kwh": _num(last["measured_kwh"]), "expected_kwh": _num(last["expected_kwh"]),
            "pr_unlimited": _num(last["pr_unlimited"]), "pr_smooth": _num(last["pr_smooth"]),
            "soiling_index": _num(last["soiling_index"]), "pr_vs_month": _num(last["pr_vs_month"]),
            "limit_loss_kwh": _num(last["limit_loss_kwh"]), "health_loss_kwh": _num(last["health_loss_kwh"]),
            "outage_loss_kwh": _num(last["outage_loss_kwh"]),
        })
        # daily rules on the last N closed days
        end_utc = (day_t + pd.Timedelta(days=1)).tz_localize("Australia/Darwin").tz_convert("UTC")
        f, s = self.health["fault"], self.health["soiling"]
        tail_f = self.days["pr_vs_month"].tail(f["min_days"])
        tail_s = self.days["soiling_index"].tail(s["min_days"])
        self._daily_alarm("FAULT", len(tail_f) == f["min_days"] and bool((tail_f < f["drop_below"]).all()),
                          day_t - pd.Timedelta(days=f["min_days"] - 1), end_utc)
        self._daily_alarm("SOILING", len(tail_s) == s["min_days"] and bool((tail_s < s["alert_below"]).all()),
                          day_t - pd.Timedelta(days=s["min_days"] - 1), end_utc)

    def _daily_alarm(self, name, active, first_day, end_utc):
        cfg = self.rt["alarms"][name]
        if active and name not in self.open_ids:
            self.open_ids[name] = self.store.open_alarm({
                "type": name, "severity": cfg["severity"], "confidence": cfg.get("confidence", "normal"),
                "start_utc": pd.Timestamp(first_day).tz_localize("Australia/Darwin").tz_convert("UTC").isoformat(),
                "message": cfg["message"],
                "recommendation": cfg["recommendation"]})
        elif not active and name in self.open_ids:
            self.store.close_alarm(self.open_ids.pop(name), end_utc.isoformat())

    # ------------------------------------------------------------------ state for the API
    def _save_state(self, t: pd.Timestamp):
        today = pd.DataFrame(self.today)
        both = today.dropna(subset=["p_ac_kw", "p_expected_cal_kw"]) if len(today) else today
        self.store.set_state("now", {
            "time_utc": t.isoformat(), "time_local": (t.tz_convert("Australia/Darwin")).isoformat(),
            "step": self.last,
            "today": {
                "measured_kwh": float(both["p_ac_kw"].clip(lower=0).sum() / 12) if len(both) else 0.0,
                "expected_kwh": float(both["p_expected_cal_kw"].sum() / 12) if len(both) else 0.0,
            },
            "open_alarms": sorted(self.open_ids),
        })

    def flush(self):
        self.store.commit()
