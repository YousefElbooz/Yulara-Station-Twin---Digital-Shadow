"""
Step 6: run the twin.

Normal use (keeps running; "now" from config/twin.yaml -> runtime.mode):
  .venv\\Scripts\\python scripts\\run_twin.py
Demo at a chosen moment, 60x real speed:
  .venv\\Scripts\\python scripts\\run_twin.py --mode speed --start 2025-10-04T06:00 --speed 60
Test: process a period as fast as possible and print what happened:
  .venv\\Scripts\\python scripts\\run_twin.py --fast --start 2025-10-04T00:00 --until 2025-10-09T00:00 --reset

Times given on the command line are local Yulara time (ACST).
The twin always starts at local midnight of its first day, so 'today' is complete.
"""
import os

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import argparse
import sys
import time
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.health.indicators import LOCAL  # noqa: E402
from backend.models.hub import PrecomputedPredictions  # noqa: E402
from backend.twin.clock import STEP, TZ, SimClock  # noqa: E402
from backend.twin.engine import TwinEngine  # noqa: E402
from backend.twin.source import HistorySource  # noqa: E402
from backend.twin.store import Store  # noqa: E402

BASE_DAY_COLS = ["measured_kwh", "expected_kwh", "expected_full_day_kwh", "coverage", "unlimited_samples",
                 "pr_unlimited", "equipment_temp_max_c", "equipment_hot_hours", "rain_mm"]


def load_yaml(name):
    return yaml.safe_load((ROOT / "config" / name).read_text(encoding="utf-8"))


def build(args):
    station, physics, twin = load_yaml("station.yaml"), load_yaml("physics.yaml"), load_yaml("twin.yaml")
    cal = load_yaml("calibration.yaml")
    rt = twin["runtime"]
    mode = args.mode or rt["mode"]
    live_weather = mode == "live-weather"
    clock = SimClock("realtime" if live_weather else mode, rt["data_until"], args.start or rt["speed_start"],
                     args.speed or rt["speed_factor"])

    if args.fast:
        first = pd.Timestamp(args.start, tz=TZ).tz_convert("UTC")
    else:
        first = clock.now()
    first_local_midnight = first.tz_convert(TZ).normalize()
    first = first_local_midnight.tz_convert("UTC") + STEP

    days = pd.read_parquet(ROOT / twin["health"]["output_file"])[BASE_DAY_COLS]
    days = days[days.index < first_local_midnight.tz_localize(None)]

    era5 = pd.read_csv(ROOT / "data/era5/era5_hourly_site_utc.csv", parse_dates=["time"]).set_index("time")
    rain = era5["era5_precip_mm"].groupby((era5.index + LOCAL).date).sum()
    rain.index = pd.to_datetime(rain.index)

    store = Store(ROOT / rt["db_file"], reset=args.reset)
    store.set_state("meta", {"mode": "fast" if args.fast else mode,
                             "source": "Open-Meteo live weather (no plant feed)" if live_weather else "history (DKASC file, replayed)",
                             "calibration": cal.get("version"), "started_local": str(first.tz_convert(TZ)),
                             "speed_factor": clock.speed_factor if mode == "speed" else 1})
    pred_file = ROOT / "data/clean/ml_predictions_5min.parquet"
    models = PrecomputedPredictions(pred_file) if pred_file.exists() else None
    engine = TwinEngine(station, physics, {"dc_loss_fraction": cal["dc_loss_fraction"]}, twin, store, days, rain,
                        models=models)
    if live_weather:
        from backend.twin.live_weather import LiveWeatherSource
        loc = station["location"]
        source = LiveWeatherSource(loc["latitude"], loc["longitude"])
        engine.plant_feed = False
    else:
        source = HistorySource(ROOT, getattr(args, "data_from", None) or rt["data_from"])
    return engine, source, clock, store, first, rt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["mirror", "speed"])
    ap.add_argument("--start", help="local time at Yulara, e.g. 2025-10-04T06:00")
    ap.add_argument("--until", help="local time, with --fast")
    ap.add_argument("--speed", type=float)
    ap.add_argument("--fast", action="store_true", help="process --start..--until as fast as possible and exit")
    ap.add_argument("--reset", action="store_true", help="start with an empty twin database")
    args = ap.parse_args()

    engine, source, clock, store, t, rt = build(args)
    print(f"twin starts at {t.tz_convert(TZ)} (local); data {source.first.tz_convert(TZ)} .. {source.last.tz_convert(TZ)}")

    if args.fast:
        until = pd.Timestamp(args.until, tz=TZ).tz_convert("UTC")
        n, t0 = 0, time.time()
        seen_alarms = 0
        while t <= until:
            engine.step(t, source.get(t))
            t += STEP
            n += 1
            rows = store.con.execute("SELECT id, type, severity, start_utc, end_utc FROM alarms ORDER BY id").fetchall()
            for a in rows[seen_alarms:]:
                print(f"  alarm opened: {a[1]} ({a[2]}) from {pd.Timestamp(a[3]).tz_convert(TZ)}")
            seen_alarms = len(rows)
        engine._close_day()
        engine.flush()
        print(f"processed {n:,} steps in {time.time() - t0:.1f} s")
        return

    print(f"running in '{clock.mode}' mode; Ctrl+C to stop")
    try:
        while True:
            target = clock.now()
            while t <= target:
                engine.step(t, source.get(t))
                t += STEP
            engine.flush()
            time.sleep(rt["tick_seconds"])
    except KeyboardInterrupt:
        engine.flush()
        print("stopped")


if __name__ == "__main__":
    main()
