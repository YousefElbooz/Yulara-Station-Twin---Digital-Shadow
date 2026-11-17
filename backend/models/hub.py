"""
Model hub: what the twin asks for the ML forecasts at a given step.

Now (history replay): forecasts are computed once for the whole replay period by
scripts/predict_ml_models.py, through the same adapters, and looked up by time here.
Later (live): the same keys come from running the adapters on the latest week of data.
"""
from __future__ import annotations

import math
from pathlib import Path

import pandas as pd

MODEL_KEYS = ["ridge", "random_forest", "xgboost", "lightgbm", "pinn_dayahead",
              "lightgbm_nowcast", "pinn_nowcast", "stacking"]


class PrecomputedPredictions:
    def __init__(self, path: Path):
        df = pd.read_parquet(path)
        self.df = df[[f"pred_{k}" for k in MODEL_KEYS]].rename(columns=lambda c: c[5:])
        self.first, self.last = self.df.index.min(), self.df.index.max()

    def get(self, t: pd.Timestamp) -> dict[str, float | None]:
        if t not in self.df.index:
            return {}
        row = self.df.loc[t]
        return {k: (None if (v is None or math.isnan(v)) else float(v)) for k, v in row.items()}
