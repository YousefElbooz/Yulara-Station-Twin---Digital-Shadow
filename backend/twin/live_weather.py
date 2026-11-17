"""
Live weather for the twin from Open-Meteo (https://open-meteo.com, free, no key, CC BY 4.0).

This is the "live weather" mode: the clock is the real time now, the weather is live, and the calibrated
physics says what the plant SHOULD be producing now. There is no live plant power (the DKASC feed is not
connected, decision Q7), so measured power is empty and plant alarms (OFFLINE, OUTAGE) are not judged.

Notes on the data (shown on the site):
- Open-Meteo values are weather-MODEL values (its "best match" model for the location), not measurements.
- Outside Europe / North America the 15-minute values are interpolated from hourly model output.
- shortwave_radiation is the mean over the PRECEDING 15 minutes, which matches the station file's
  end-of-interval labels; values are interpolated to the twin's 5-minute steps.

Returns the same dict as HistorySource.get(t), so the engine does not change.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.parse
import urllib.request

import numpy as np
import pandas as pd

URL = "https://api.open-meteo.com/v1/forecast"
REFRESH_S = 600   # Open-Meteo updates its models hourly; asking every 10 min is plenty


class LiveWeatherSource:
    name = "open-meteo"

    def __init__(self, lat: float, lon: float):
        self.lat, self.lon = lat, lon
        self.df: pd.DataFrame | None = None     # 5-min, UTC index
        self.hourly: pd.DataFrame | None = None  # cloud cover, rain per hour, UTC index
        self.fetched_at: float = 0.0
        self.error: str | None = None
        self._lock = threading.Lock()
        self.refresh(force=True)

    # ------------------------------------------------------------------ fetching
    def refresh(self, force: bool = False):
        if not force and time.time() - self.fetched_at < REFRESH_S:
            return
        q = {
            "latitude": self.lat, "longitude": self.lon,
            "minutely_15": "shortwave_radiation,temperature_2m,wind_speed_10m,wind_direction_10m,precipitation",
            "hourly": "cloud_cover,precipitation",
            "wind_speed_unit": "ms", "timezone": "UTC", "past_days": 1, "forecast_days": 2,
        }
        try:
            req = urllib.request.Request(f"{URL}?{urllib.parse.urlencode(q)}", headers={"User-Agent": "yulara-twin/0.1"})
            with urllib.request.urlopen(req, timeout=20) as r:
                d = json.loads(r.read().decode("utf-8"))
            m = pd.DataFrame(d["minutely_15"])
            m.index = pd.to_datetime(m.pop("time")).dt.tz_localize("UTC")
            # 15-min -> 5-min steps (linear); the 5-min step ending at t takes the interpolated value at t
            idx = pd.date_range(m.index[0], m.index[-1], freq="5min")
            m5 = m.reindex(m.index.union(idx)).interpolate(method="time").reindex(idx)
            # wind direction: interpolate as a vector so 350 -> 10 degrees does not swing through 180
            rad = np.deg2rad(m["wind_direction_10m"])
            u = pd.Series(np.sin(rad), index=m.index).reindex(m.index.union(idx)).interpolate(method="time").reindex(idx)
            v = pd.Series(np.cos(rad), index=m.index).reindex(m.index.union(idx)).interpolate(method="time").reindex(idx)
            m5["wind_direction_10m"] = (np.rad2deg(np.arctan2(u, v)) + 360) % 360
            h = pd.DataFrame(d["hourly"])
            h.index = pd.to_datetime(h.pop("time")).dt.tz_localize("UTC")
            with self._lock:
                self.df, self.hourly = m5, h
                self.fetched_at = time.time()
                self.error = None
        except Exception as ex:  # noqa: BLE001 - keep the last good data; the API reports the error
            self.error = f"{type(ex).__name__}: {ex}"
            if self.df is None:
                raise

    # ------------------------------------------------------------------ same interface as HistorySource
    def get(self, t: pd.Timestamp) -> dict | None:
        self.refresh()
        with self._lock:
            df = self.df
        if df is None or t not in df.index:
            return None
        r = df.loc[t]
        num = lambda v: None if pd.isna(v) else float(v)  # noqa: E731
        return {
            "time_utc": t,
            "p_ac_kw": None,                       # no live plant feed
            "ghi_wm2": num(r["shortwave_radiation"]), "pyrano1_wm2": None,
            "t_air_c": num(r["temperature_2m"]), "wind_ms": num(r["wind_speed_10m"]),
            "wind_dir_deg": num(r["wind_direction_10m"]),
            "t_probe1_c": None, "t_probe2_c": None, "sun_elevation_deg": None,
            "flag_gap": False, "flag_stuck_power": False,
            "ghi_model_wm2": num(r["shortwave_radiation"]), "t_air_model_c": num(r["temperature_2m"]),
            "wind_model_ms": num(r["wind_speed_10m"]),
            "src_ghi": "open-meteo", "src_temp": "open-meteo", "src_wind": "open-meteo",
        }

    def rain_and_cloud(self, t: pd.Timestamp) -> tuple[float | None, float | None]:
        """Rain (mm in the hour ending at the next full hour) and cloud cover 0-1, for the scene."""
        with self._lock:
            h = self.hourly
        if h is None:
            return None, None
        hour = t.tz_convert("UTC").ceil("h")
        if hour not in h.index:
            return None, None
        r = h.loc[hour]
        rain = None if pd.isna(r["precipitation"]) else round(float(r["precipitation"]), 2)
        cloud = None if pd.isna(r["cloud_cover"]) else round(float(r["cloud_cover"]) / 100, 2)
        return rain, cloud

    @property
    def last(self) -> pd.Timestamp | None:
        return None if self.df is None else self.df.index[-1]
