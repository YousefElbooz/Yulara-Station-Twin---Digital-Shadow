"""
The twin's clock: which 5-minute step is "now".

Until the DKASC live feed is connected, "now" is taken from the station history:
  mirror  today's date and local time at Yulara, in the latest year that has data.
          Runs at real speed, so the page looks live.
  speed   starts at a chosen local moment and runs faster than real time (demos, tests).
Steps are labelled at the END of their 5-minute interval, like the station file.
"""
from __future__ import annotations

import time

import pandas as pd

STEP = pd.Timedelta(minutes=5)
TZ = "Australia/Darwin"


class SimClock:
    def __init__(self, mode: str, data_until_local: str, speed_start_local: str | None = None,
                 speed_factor: float = 60.0):
        self.mode = mode
        self.data_until = pd.Timestamp(data_until_local, tz=TZ).tz_convert("UTC")
        self.speed_factor = speed_factor
        self._wall0 = time.time()
        if mode == "speed":
            self._sim0 = pd.Timestamp(speed_start_local, tz=TZ).tz_convert("UTC")
        elif mode not in ("mirror", "realtime"):
            raise ValueError(f"unknown clock mode {mode}")

    def now(self) -> pd.Timestamp:
        """Latest completed 5-min step (UTC), never beyond the end of the data."""
        if self.mode == "realtime":   # live weather: the real time now
            return pd.Timestamp.now(tz="UTC").floor("5min")
        if self.mode == "speed":
            t = self._sim0 + pd.Timedelta(seconds=(time.time() - self._wall0) * self.speed_factor)
        else:
            local_now = pd.Timestamp.now(tz=TZ)
            last_year = self.data_until.tz_convert(TZ).year
            for year in range(last_year, last_year - 3, -1):
                try:
                    cand = local_now.replace(year=year)
                except ValueError:          # 29 Feb in a non-leap year
                    cand = (local_now - pd.Timedelta(days=1)).replace(year=year)
                if cand.tz_convert("UTC") <= self.data_until:
                    break
            t = cand.tz_convert("UTC")
        return min(t.floor("5min"), self.data_until)
