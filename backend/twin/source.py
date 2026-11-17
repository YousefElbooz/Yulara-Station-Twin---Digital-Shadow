"""
Where the twin reads the plant's measurements from.

HistorySource serves the cleaned station history one 5-minute step at a time, exactly as a live
feed would: measured power and sensors, the weather the physics should use (with its source),
and the flags. A future LiveSource (DKASC feed + weather forecast) only has to return the same dict.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

STATION_COLS = ["p_ac_kw", "ghi_wm2", "pyrano1_wm2", "t_air_c", "wind_ms", "wind_dir_deg",
                "t_probe1_c", "t_probe2_c", "sun_elevation_deg", "flag_gap", "flag_stuck_power"]
WEATHER_COLS = ["ghi_model_wm2", "t_air_model_c", "wind_model_ms", "src_ghi", "src_temp", "src_wind"]


class HistorySource:
    name = "history"

    def __init__(self, root: Path, data_from: str):
        start = pd.Timestamp(data_from, tz="UTC")
        st = pd.read_parquet(root / "data/clean/station_5min.parquet", columns=STATION_COLS)
        wm = pd.read_parquet(root / "data/clean/weather_model_5min.parquet", columns=WEATHER_COLS)
        df = st.join(wm)
        df = df[df.index >= start]
        for c in ["src_ghi", "src_temp", "src_wind"]:
            df[c] = df[c].astype(str)
        self.df = df
        self.first, self.last = df.index.min(), df.index.max()

    def get(self, t: pd.Timestamp) -> dict | None:
        """One step as a plain dict (None outside the data). Missing values are None."""
        if t not in self.df.index:
            return None
        row = self.df.loc[t]
        out = {k: (None if (isinstance(v, float) and np.isnan(v)) else (v.item() if hasattr(v, "item") else v))
               for k, v in row.items()}
        out["time_utc"] = t
        return out
