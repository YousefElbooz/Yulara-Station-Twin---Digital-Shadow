"""
Adapters: one per trained model, all with the same interface, so the twin can run any of them
without knowing how it was built. Inputs come from backend.models.features (the ML team's own
pipeline); the contract for each model is in docs/model_contract.md.

  predict(table, rows) -> numpy array of kW for the given row positions of the model table
"""
from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np
import torch
import torch.nn as nn

from backend.models.features import PHYS_COLS


class ResidualCNNLSTM(nn.Module):
    """Same architecture as the ML team's DP-PINN (Phase A)."""

    def __init__(self, n_feat, cap_kw, cnn_channels=(32, 48), lstm_hidden=64, dropout=0.1):
        super().__init__()
        c1, c2 = cnn_channels
        self.conv = nn.Sequential(nn.Conv1d(n_feat, c1, 3, padding=1), nn.GELU(),
                                  nn.Conv1d(c1, c2, 3, padding=1), nn.GELU(), nn.Dropout(dropout))
        self.lstm = nn.LSTM(c2, lstm_hidden, batch_first=True)
        self.delta_head = nn.Sequential(nn.Linear(lstm_hidden, 32), nn.GELU(), nn.Dropout(dropout), nn.Linear(32, 1))
        self.log_eta = nn.Parameter(torch.tensor(0.0))
        self.alpha_raw = nn.Parameter(torch.tensor(0.0))
        self.cap_kw = float(cap_kw)

    def forward(self, x, base):
        h = self.conv(x.transpose(1, 2)).transpose(1, 2)
        out, _ = self.lstm(h)
        delta = self.delta_head(out[:, -1, :]).squeeze(-1)
        return nn.functional.softplus(base + delta)


class Adapter:
    key: str
    name: str
    track: str          # "day-ahead" (no recent power) or "nowcast" (uses the last hour of power)
    inputs: list[str]

    def predict(self, table, rows: np.ndarray) -> np.ndarray:
        raise NotImplementedError


class TabularAdapter(Adapter):
    def __init__(self, key, name, track, path: Path, inputs: list[str]):
        self.key, self.name, self.track, self.inputs = key, name, track, inputs
        self.model = joblib.load(path)

    def predict(self, table, rows):
        X = table[self.inputs].values[rows]
        return np.clip(self.model.predict(X), 0, None)


class PinnAdapter(Adapter):
    """Sequence model: each prediction looks at the previous 12 rows (1 hour) of the table."""

    def __init__(self, key, name, track, ckpt: Path, scaler: Path):
        ck = torch.load(ckpt, weights_only=False, map_location="cpu")
        self.key, self.name, self.track = key, name, track
        self.inputs = ck["feat_cols"]
        self.lookback, self.cap_kw = ck["lookback"], ck["CAP_KW"]
        self.g_stc, self.t_stc = ck.get("G_STC", 1000.0), ck.get("T_STC", 25.0)
        self.net = ResidualCNNLSTM(len(self.inputs), self.cap_kw)
        self.net.load_state_dict(ck["state_dict"])
        self.net.eval()
        self.scaler = joblib.load(scaler)
        self.eta, self.alpha = ck.get("eta"), ck.get("alpha")

    def base(self, table) -> np.ndarray:
        if self.track == "nowcast":
            return table["Power_lag_1"].values.astype(np.float32)
        phys = table[PHYS_COLS].values.astype(np.float32)
        ghi, tcell, degr = phys[:, 2], phys[:, 3], phys[:, 4]
        stc = np.clip(0.20 * ghi * (1.0 + -0.004 * (tcell - self.t_stc)) * degr * (self.cap_kw / self.g_stc), 0, None)
        return (0.65 * stc + 0.35 * table["Power_lag_288"].values.astype(np.float32)).astype(np.float32)

    @torch.no_grad()
    def predict(self, table, rows, batch=4096):
        X = self.scaler.transform(table[self.inputs].values).astype(np.float32)
        base = self.base(table)
        rows = np.asarray(rows)
        out = np.full(len(rows), np.nan)
        ok = rows >= self.lookback - 1
        r_ok = rows[ok]
        preds = []
        for i in range(0, len(r_ok), batch):
            r = r_ok[i:i + batch]
            win = np.stack([X[t - self.lookback + 1:t + 1] for t in r])
            preds.append(self.net(torch.from_numpy(win), torch.from_numpy(base[r])).numpy())
        if preds:
            out[ok] = np.concatenate(preds)
        return np.clip(out, 0, None)


class StackingAdapter(Adapter):
    """Ridge meta-model over five base models (their test-time predictions)."""

    def __init__(self, path: Path, members: list[Adapter]):
        self.key, self.name, self.track = "stacking", "Stacking ensemble", "nowcast"
        self.meta = joblib.load(path)
        self.members = members
        self.inputs = [f"prediction of {m.key}" for m in members]

    def predict_from(self, member_preds: list[np.ndarray]) -> np.ndarray:
        return np.clip(self.meta.predict(np.column_stack(member_preds)), 0, None)


def load_all(model_dir: Path, fc: list[str], fnc: list[str]) -> dict[str, Adapter]:
    a = {
        "ridge": TabularAdapter("ridge", "Ridge regression", "day-ahead", model_dir / "ridge.pkl", fc),
        "random_forest": TabularAdapter("random_forest", "Random forest", "day-ahead", model_dir / "random_forest.pkl", fc),
        "xgboost": TabularAdapter("xgboost", "XGBoost", "day-ahead", model_dir / "xgboost.pkl", fc),
        "lightgbm": TabularAdapter("lightgbm", "LightGBM", "day-ahead", model_dir / "lightgbm.pkl", fc),
        "pinn_dayahead": PinnAdapter("pinn_dayahead", "DP-PINN day-ahead", "day-ahead",
                                     model_dir / "cnn_lstm_pinn_dayahead.pt", model_dir / "pinn_dayahead_x_scaler.pkl"),
        "lightgbm_nowcast": TabularAdapter("lightgbm_nowcast", "LightGBM nowcast", "nowcast", model_dir / "lightgbm_nowcast.pkl", fnc),
        "pinn_nowcast": PinnAdapter("pinn_nowcast", "DP-PINN nowcast", "nowcast",
                                    model_dir / "cnn_lstm_pinn_nowcast.pt", model_dir / "pinn_x_scaler.pkl"),
    }
    a["stacking"] = StackingAdapter(model_dir / "stacking_meta.pkl",
                                    [a["random_forest"], a["xgboost"], a["lightgbm"], a["lightgbm_nowcast"], a["pinn_nowcast"]])
    return a
