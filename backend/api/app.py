"""
The twin's API (step 8). The website only talks to this; it never computes anything itself.

Start (from the project folder):
  .venv\\Scripts\\python -m uvicorn backend.api.app:app --port 8000
Interactive docs: http://localhost:8000/docs

The twin loop runs inside this process (backend/twin/runner.py) and writes to SQLite;
the endpoints read from SQLite and from the files made by steps 1-7. Set TWIN_RUN=0 to serve
the stored state without running the loop.
"""
from __future__ import annotations

import copy
import json
import math
import os
import sqlite3
import threading
from typing import Literal
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import pandas as pd
import pvlib
import yaml
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.models.hub import MODEL_KEYS
from backend.physics.pv_chain import simulate
from backend.twin.runner import TwinRunner
from backend.twin.store import reader

ROOT = Path(__file__).resolve().parents[2]
TZ = "Australia/Darwin"
MODEL_NAMES = {"ridge": "Ridge regression", "random_forest": "Random forest", "xgboost": "XGBoost",
               "lightgbm": "LightGBM", "pinn_dayahead": "DP-PINN day-ahead", "lightgbm_nowcast": "LightGBM nowcast",
               "pinn_nowcast": "DP-PINN nowcast", "stacking": "Stacking ensemble"}
MODEL_TRACK = {"ridge": "day-ahead", "random_forest": "day-ahead", "xgboost": "day-ahead", "lightgbm": "day-ahead",
               "pinn_dayahead": "day-ahead", "lightgbm_nowcast": "nowcast", "pinn_nowcast": "nowcast", "stacking": "nowcast"}


def cfg(name: str) -> dict:
    return yaml.safe_load((ROOT / "config" / name).read_text(encoding="utf-8"))


def db_path() -> Path:
    return ROOT / cfg("twin.yaml")["runtime"]["db_file"]


def clean(v):
    """JSON-safe numbers (NaN -> None)."""
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


def local(ts: str | None) -> str | None:
    return pd.Timestamp(ts).tz_convert(TZ).isoformat() if ts else None


runner: TwinRunner | None = None
twin_config: dict = {}
_restart_lock = threading.Lock()
DATA_FIRST_LOCAL = "2016-04-01T00:05"   # first step in the station file (local time)
MODELS_FIRST_LOCAL = "2022-10-30"       # ML predictions exist from here (validation + test period)


def start_twin(conf: dict):
    """Stop the running twin (if any) and start a new one. conf: {mode: live|replay, start, speed}."""
    global runner, twin_config
    rt = cfg("twin.yaml")["runtime"]
    if runner is not None:
        runner.stop()
        runner.join(timeout=20)
    if conf["mode"] == "replay":
        start = pd.Timestamp(conf["start"])
        # load history from 2 days before the chosen moment if that is earlier than the default window
        data_from = None
        if start - pd.Timedelta(days=2) < pd.Timestamp(rt["data_from"]):
            data_from = (start - pd.Timedelta(days=2)).strftime("%Y-%m-%d")
        tick = 2 if conf["speed"] >= 20 else None
        runner = TwinRunner(mode="speed", reset=True, start=conf["start"], speed=conf["speed"], tick=tick,
                            data_from=data_from)
    elif conf["mode"] == "weather":
        runner = TwinRunner(mode="live-weather", reset=True)
    else:
        runner = TwinRunner(mode="mirror", reset=True)
    runner.start()
    twin_config = {**conf, "applied_at_utc": pd.Timestamp.now(tz="UTC").isoformat()}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if os.environ.get("TWIN_RUN", "1") != "0":
        if os.environ.get("TWIN_PROFILE") == "demo":
            d = cfg("twin.yaml")["runtime"]["demo"]
            start_twin({"mode": "replay", "start": d["start"], "speed": float(d["speed_factor"])})
        elif os.environ.get("TWIN_PROFILE") == "live-weather":
            start_twin({"mode": "weather", "start": None, "speed": 1.0})
        else:
            start_twin({"mode": "live", "start": None, "speed": 1.0})
    yield
    if runner:
        runner.stop()


app = FastAPI(title="Yulara Station Twin API", version="0.1.0", lifespan=lifespan,
              description="Digital shadow of Yulara 1 – Desert Gardens (DKA Solar Centre). Read-only views of the "
                          "running twin, plus what-if runs of the calibrated physics.")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://localhost:3000",
                                                  "http://127.0.0.1:5173"], allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(sqlite3.OperationalError)
async def _db_busy(_req, ex):
    # happens for a moment while the twin restarts (its tables are recreated)
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=503, content={"detail": f"The twin is restarting ({ex})."})


def con():
    p = db_path()
    if not p.exists():
        raise HTTPException(503, "The twin has not written any state yet; it is still starting.")
    return reader(p)


# ------------------------------------------------------------------ status
@app.get("/api/health", summary="Is the API up, and is the twin loop running?")
def health():
    src = getattr(runner, "source", None)
    live = None
    if src is not None and hasattr(src, "fetched_at"):
        live = {"provider": "Open-Meteo", "fetched_utc": pd.Timestamp(src.fetched_at, unit="s", tz="UTC").isoformat() if src.fetched_at else None,
                "error": src.error}
    return {"api": "ok", "twin": runner.status if runner else "not started (TWIN_RUN=0)", "config": twin_config, "live_weather": live,
            "error": runner.error if runner else None,
            "last_step_local": runner.last_step.tz_convert(TZ).isoformat() if runner and runner.last_step is not None else None}


@app.get("/api/now", summary="The plant right now: latest step, today so far, open alarms")
def now():
    c = con()
    row = c.execute("SELECT value FROM state WHERE key='now'").fetchone()
    meta = c.execute("SELECT value FROM state WHERE key='meta'").fetchone()
    if not row:
        raise HTTPException(503, "No step processed yet.")
    state = json.loads(row["value"])
    alarms = [dict(r) for r in c.execute("SELECT * FROM alarms WHERE is_open=1 ORDER BY id DESC")]
    for a in alarms:
        a["start_local"] = local(a["start_utc"])
    state["open_alarms"] = alarms
    state["meta"] = json.loads(meta["value"]) if meta else None
    return state


# ------------------------------------------------------------------ twin settings (site's settings panel)
class TwinConfigReq(BaseModel):
    mode: Literal["live", "replay", "weather"] = Field(..., description="live = today's date and time at Yulara, in the latest "
                                            "year with data; replay = start from a chosen moment; weather = the real time "
                                            "now with live Open-Meteo weather and expected power (no plant feed)")
    start: str | None = Field(None, description="Local time at Yulara for replay, e.g. 2025-10-04T08:15")
    speed: float = Field(1.0, ge=1, le=600, description="Replay speed: simulated seconds per real second")


@app.get("/api/twin/config", summary="How the twin is running now, and the allowed range")
def get_twin_config():
    rt = cfg("twin.yaml")["runtime"]
    return {"config": twin_config, "status": runner.status if runner else None,
            "limits": {"first_local": DATA_FIRST_LOCAL, "last_local": rt["data_until"], "models_from_local": MODELS_FIRST_LOCAL,
                       "speeds": [1, 30, 90, 300]}}


@app.post("/api/twin/config", summary="Restart the twin: live, or replay from a chosen local date and time")
def set_twin_config(req: TwinConfigReq):
    if os.environ.get("TWIN_RUN", "1") == "0":
        raise HTTPException(409, "The twin loop is disabled (TWIN_RUN=0).")
    rt = cfg("twin.yaml")["runtime"]
    conf = {"mode": req.mode, "start": None, "speed": 1.0}
    if req.mode == "replay":
        if not req.start:
            raise HTTPException(400, "Replay needs a start time.")
        try:
            st = pd.Timestamp(req.start)
        except Exception as ex:  # noqa: BLE001
            raise HTTPException(400, f"Bad start time: {ex}") from ex
        if st.tzinfo is not None:
            st = st.tz_convert(TZ).tz_localize(None)
        st = st.floor("5min")
        if not (pd.Timestamp(DATA_FIRST_LOCAL) <= st <= pd.Timestamp(rt["data_until"])):
            raise HTTPException(400, f"Start must be between {DATA_FIRST_LOCAL} and {rt['data_until']} (Yulara time).")
        conf = {"mode": "replay", "start": st.strftime("%Y-%m-%dT%H:%M"), "speed": float(req.speed)}
    with _restart_lock:
        start_twin(conf)
    return {"config": twin_config, "status": runner.status}


# ------------------------------------------------------------------ history views
@app.get("/api/series", summary="5-minute series: measured, physics, ML forecasts, weather")
def series(hours: float = Query(24, gt=0, le=24 * 7, description="Hours back from the twin's 'now'")):
    c = con()
    last = c.execute("SELECT MAX(time_utc) AS t FROM steps").fetchone()["t"]
    if last is None:
        return {"points": []}
    start = (pd.Timestamp(last) - pd.Timedelta(hours=hours)).isoformat()
    steps = pd.read_sql("SELECT * FROM steps WHERE time_utc > ? ORDER BY time_utc", c, params=[start])
    preds = pd.read_sql("SELECT time_utc, model, kw FROM predictions WHERE time_utc > ?", c, params=[start])
    wide = preds.pivot(index="time_utc", columns="model", values="kw") if len(preds) else pd.DataFrame()
    pts = []
    for r in steps.to_dict("records"):
        m = wide.loc[r["time_utc"]].to_dict() if r["time_utc"] in wide.index else {}
        r = {k: clean(v) for k, v in r.items()}
        r["time_local"] = local(r["time_utc"])
        r["models"] = {k: clean(v) for k, v in m.items()}
        pts.append(r)
    return {"from_utc": start, "to_utc": last, "points": pts}


@app.get("/api/days", summary="Closed days processed by the running twin")
def days(limit: int = Query(60, gt=0, le=1000)):
    c = con()
    rows = [dict(r) for r in c.execute("SELECT * FROM days ORDER BY date DESC LIMIT ?", [limit])][::-1]
    for r in rows:
        r["source"] = "twin"
    # before the twin started, the same daily numbers come from the step 5 history
    if len(rows) < limit:
        first = rows[0]["date"] if rows else _twin_today(c)
        h = _health_daily()
        h = h[h.index < pd.Timestamp(first)].tail(limit - len(rows))
        cols = ["measured_kwh", "expected_kwh", "pr_unlimited", "pr_smooth", "soiling_index", "pr_vs_month",
                "limit_loss_kwh", "health_loss_kwh", "outage_loss_kwh"]
        hist = [{"date": d.strftime("%Y-%m-%d"), **{k: clean(float(r[k])) for k in cols}, "source": "history"}
                for d, r in h[cols].iterrows()]
        rows = hist + rows
    return {"days": [{k: clean(v) for k, v in r.items()} for r in rows]}


def _twin_today(c) -> str:
    row = c.execute("SELECT value FROM state WHERE key='now'").fetchone()
    if not row:
        return "2100-01-01"
    return pd.Timestamp(json.loads(row["value"])["time_local"]).strftime("%Y-%m-%d")


@app.get("/api/alarms", summary="Alarm log")
def alarms(open_only: bool = False, limit: int = Query(100, gt=0, le=1000)):
    c = con()
    q = "SELECT * FROM alarms" + (" WHERE is_open=1" if open_only else "") + " ORDER BY id DESC LIMIT ?"
    out = []
    for r in c.execute(q, [limit]):
        a = dict(r)
        a["start_local"], a["end_local"] = local(a["start_utc"]), local(a["end_utc"])
        out.append(a)
    return {"alarms": out}


@lru_cache(maxsize=1)
def _health_daily():
    return pd.read_parquet(ROOT / cfg("twin.yaml")["health"]["output_file"])


@app.get("/api/health-history", summary="2016-2026 plant health from step 5: yearly energy split and events")
def health_history():
    d = _health_daily()
    y = d.groupby(d.index.year).agg(expected=("expected_kwh", "sum"), measured=("measured_kwh", "sum"),
                                    health_loss=("health_loss_kwh", "sum"), limit_loss=("limit_loss_kwh", "sum"),
                                    outage_loss=("outage_loss_kwh", "sum"), pr=("pr_unlimited", "median"))
    years = [{"year": int(k), **{c: clean(round(float(v) / (1000 if c != "pr" else 1), 3)) for c, v in r.items()}}
             for k, r in y.iterrows()]
    ev = pd.read_csv(ROOT / "data/clean/health_events.csv")
    daily = d[["measured_kwh", "expected_kwh", "pr_smooth", "soiling_index", "limit_loss_kwh", "outage_day"]].copy()
    daily.index = daily.index.strftime("%Y-%m-%d")
    return {"units": "MWh (pr: ratio)", "years": years,
            "events": ev.to_dict("records"),
            "daily": [{"date": k, **{c: clean(float(v)) for c, v in r.items()}} for k, r in daily.iterrows()]}


# ------------------------------------------------------------------ station and models
@app.get("/api/station", summary="Station facts, calibration and layout (values marked when calculated)")
def station():
    st = cfg("station.yaml")
    cal = cfg("calibration.yaml")
    st["calculated_values"] = ["inverter.count", "inverter.ac_capacity_kw", "array.modules_deep_portrait"]
    st["calibration"] = {k: cal[k] for k in ["version", "fitted_on_years", "dc_loss_fraction", "test_year",
                                               "test_unlimited_rmse_kw", "not_calibrated"] if k in cal}
    st["sources_doc"] = "docs/station_facts.md"
    return st


@app.get("/api/models", summary="The ML models in the twin and how they score")
def models():
    summ = json.loads((ROOT / "models_store/friend_v1/run_summary.json").read_text(encoding="utf-8"))
    trained = {r["Model"]: r for r in summ["results"]}
    name_in_summary = {"ridge": "Ridge Regression", "random_forest": "Random Forest", "xgboost": "XGBoost",
                       "lightgbm": "LightGBM", "pinn_dayahead": "DP-PINN (day-ahead)", "lightgbm_nowcast": "Nowcast LightGBM",
                       "pinn_nowcast": "DP-PINN (nowcast)", "stacking": "Stacking Ensemble"}
    comp_file = ROOT / "data/clean/model_comparison_2025.json"
    comp = json.loads(comp_file.read_text(encoding="utf-8")) if comp_file.exists() else {}
    out = []
    for k in MODEL_KEYS:
        t = trained.get(name_in_summary[k], {})
        out.append({"key": k, "name": MODEL_NAMES[k], "track": MODEL_TRACK[k],
                    "test_rmse_kw_training_split": clean(t.get("RMSE")), "r2_training_split": clean(t.get("R²")),
                    "y2025": comp.get(k)})
    out.append({"key": "physics", "name": "Calibrated physics (twin)", "track": "physics", "y2025": comp.get("physics")})
    return {"contract": "docs/model_contract.md", "split": summ.get("split"), "models": out}


# ------------------------------------------------------------------ 3D scene
@lru_cache(maxsize=1)
def _era5_hourly():
    e = pd.read_csv(ROOT / "data/era5/era5_hourly_site_utc.csv", parse_dates=["time"], usecols=["time", "era5_precip_mm", "era5_tcc"])
    return e.set_index("time")


def _rain_and_cloud(t_utc: pd.Timestamp) -> tuple[float | None, float | None]:
    """ERA5 rain (mm in the hour ending at the stamp) and total cloud cover (0-1) for the step's hour."""
    e = _era5_hourly()
    hour = t_utc.tz_convert("UTC").tz_localize(None).ceil("h")
    if hour not in e.index:
        return None, None
    r = e.loc[hour]
    return clean(round(float(r["era5_precip_mm"]), 2)), clean(round(float(r["era5_tcc"]), 2))


@app.get("/api/scene", summary="Everything the 3D station view animates, for the twin's current step")
def scene():
    c = con()
    st = json.loads(c.execute("SELECT value FROM state WHERE key='now'").fetchone()["value"])
    step = st["step"] or {}
    t = pd.Timestamp(st["time_utc"])
    station_cfg = cfg("station.yaml")
    loc = station_cfg["location"]
    sp = pvlib.solarposition.get_solarposition(pd.DatetimeIndex([t - pd.Timedelta(minutes=2.5)]),
                                               loc["latitude"], loc["longitude"], altitude=loc["altitude_m"]).iloc[0]
    last_day = c.execute("SELECT soiling_index, pr_smooth FROM days ORDER BY date DESC LIMIT 1").fetchone()
    if last_day is None or last_day["soiling_index"] is None:
        h = _health_daily()
        h = h[h.index < pd.Timestamp(st["time_local"][:10])]["soiling_index"].dropna()
        last_day = {"soiling_index": float(h.iloc[-1])} if len(h) else None
    open_alarms = [r["type"] for r in c.execute("SELECT type FROM alarms WHERE is_open=1")]
    gamma = station_cfg["module"]["gamma_pdc_per_c"]
    tcell = step.get("t_cell_c")
    src = getattr(runner, "source", None)
    if twin_config.get("mode") == "weather" and src is not None and hasattr(src, "rain_and_cloud"):
        rain, cloud = src.rain_and_cloud(t)
        rain_source = "Open-Meteo (hourly model)"
    else:
        rain, cloud = _rain_and_cloud(t)
        rain_source = "ERA5 (hourly, site grid cell)"
    return {
        "time_local": st["time_local"],
        "sun": {"elevation_deg": clean(float(sp["apparent_elevation"])), "azimuth_deg": clean(float(sp["azimuth"]))},
        "weather": {"ghi_wm2": step.get("ghi_wm2"), "poa_wm2": step.get("poa_wm2"), "t_air_c": step.get("t_air_c"),
                    "wind_ms": step.get("wind_ms"), "wind_from_deg": step.get("wind_dir_deg"),
                    "source": step.get("src_weather"),
                    "rain_mm_h": rain, "cloud_cover": cloud, "rain_source": rain_source},
        "panels": {"t_cell_c": tcell,
                   "heat_loss_pct": clean(round(-100 * gamma * (tcell - 25), 2))
                   if tcell is not None and tcell > 25 and step.get("status") != "night" else 0.0,
                   "dust_index": clean(last_day["soiling_index"]) if last_day else None, "dust_confidence": "low"},
        "power": {"measured_kw": step.get("measured_kw"), "expected_kw": step.get("expected_kw"),
                  "held_back_kw": clean(max(0.0, (step.get("expected_kw") or 0) - (step.get("measured_kw") or 0)))
                  if step.get("status") == "limited" else 0.0,
                  "status": step.get("status")},
        "equipment": {"temp_c": step.get("equipment_temp_c")},
        "alarms": open_alarms,
        "layout": {"rows": station_cfg["array"]["rows"], "modules": station_cfg["array"]["modules"],
                   "tilt_deg": station_cfg["array"]["tilt_deg"], "azimuth_deg": station_cfg["array"]["azimuth_deg"],
                   "inverters": station_cfg["inverter"]["count"], "inverters_calculated": True,
                   "reference": "docs/station_facts.md (layout section)"},
    }


# ------------------------------------------------------------------ what-if
class WhatIf(BaseModel):
    date: str = Field(..., description="Local date at Yulara, e.g. 2025-07-15")
    temp_delta_c: float = Field(0.0, ge=-20, le=20, description="Add to air temperature")
    soiling_pct: float = Field(0.0, ge=0, le=50, description="Extra loss from dust, percent")
    tilt_deg: float | None = Field(None, ge=0, le=60)
    azimuth_deg: float | None = Field(None, ge=0, lt=360, description="0 = north")
    gamma_pdc_per_c: float | None = Field(None, ge=-0.01, le=0, description="Temperature coefficient, per °C")
    ageing_years: float = Field(0.0, ge=0, le=30, description="Extra years of ageing at 0.95% per year (step 4 trend)")


@lru_cache(maxsize=1)
def _weather():
    st = pd.read_parquet(ROOT / "data/clean/station_5min.parquet", columns=["p_ac_kw"])
    wm = pd.read_parquet(ROOT / "data/clean/weather_model_5min.parquet",
                         columns=["ghi_model_wm2", "t_air_model_c", "wind_model_ms"])
    return st.join(wm)


@app.post("/api/whatif", summary="Run the calibrated physics for one real day with changed conditions")
def whatif(req: WhatIf):
    try:
        day0 = pd.Timestamp(req.date).tz_localize(TZ)
    except Exception as ex:  # noqa: BLE001
        raise HTTPException(400, f"Bad date: {ex}") from ex
    w = _weather().loc[day0.tz_convert("UTC"):(day0 + pd.Timedelta(days=1)).tz_convert("UTC") - pd.Timedelta(minutes=1)]
    if w.empty or w["ghi_model_wm2"].notna().sum() == 0:
        raise HTTPException(404, "No weather for that date (data covers 2016-04-01 to 2026-02-19).")
    station_cfg, phys = cfg("station.yaml"), cfg("physics.yaml")
    loss0 = cfg("calibration.yaml")["dc_loss_fraction"]
    inp = w[["ghi_model_wm2", "t_air_model_c", "wind_model_ms"]].rename(
        columns={"ghi_model_wm2": "ghi_wm2", "t_air_model_c": "t_air_c", "wind_model_ms": "wind_ms"})
    base = simulate(inp, station_cfg, phys, calibration={"dc_loss_fraction": loss0})

    s2 = copy.deepcopy(station_cfg)
    if req.tilt_deg is not None:
        s2["array"]["tilt_deg"] = req.tilt_deg
    if req.azimuth_deg is not None:
        s2["array"]["azimuth_deg"] = req.azimuth_deg
    if req.gamma_pdc_per_c is not None:
        s2["module"]["gamma_pdc_per_c"] = req.gamma_pdc_per_c
    keep = (1 - loss0) * (1 - req.soiling_pct / 100) * (1 - 0.0095) ** req.ageing_years
    inp2 = inp.assign(t_air_c=inp["t_air_c"] + req.temp_delta_c)
    scen = simulate(inp2, s2, phys, calibration={"dc_loss_fraction": 1 - keep})

    pts = [{"time_local": t.tz_convert(TZ).isoformat(), "measured_kw": clean(float(m)) if pd.notna(m) else None,
            "baseline_kw": clean(float(b)), "scenario_kw": clean(float(s)),
            "t_cell_baseline_c": clean(float(tb)), "t_cell_scenario_c": clean(float(ts))}
           for t, m, b, s, tb, ts in zip(w.index, w["p_ac_kw"], base["p_expected_kw"], scen["p_expected_kw"],
                                          base["t_cell_c"], scen["t_cell_c"])]
    e = lambda s: float(s.fillna(0).sum() / 12)  # noqa: E731 - kWh from 5-min kW
    return {"request": req.model_dump(), "energy_kwh": {"measured": e(w["p_ac_kw"].clip(lower=0)),
            "baseline": e(base["p_expected_kw"]), "scenario": e(scen["p_expected_kw"])}, "points": pts}
