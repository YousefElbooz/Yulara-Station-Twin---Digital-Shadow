"""
Download ERA5 hourly single-level data for the Yulara Desert Gardens site and
build one hourly point series, the same way the ML team's notebook does
(PV_Forecasting_Analysis_Suite_ERA5.ipynb, cell "0. ERA5 download").

Kept identical on purpose, so the trained models see the same inputs:
  - the same 14 variables
  - the same area box (site +/- 0.5 deg) and the same point (-25.24, 130.99)
  - the same unit conversions and output column names

Output
  data/era5_raw/era5_YYYY_MM.nc        one file per month (cached, re-runs skip them)
  data/era5/era5_hourly_site_utc.csv   hourly point series, UTC, "hour ending" stamps

Usage (from the project folder)
  python scripts/download_era5_yulara.py            # download + build the CSV
  python scripts/download_era5_yulara.py --build    # only build the CSV from cached files

Needs
  pip install "cdsapi>=0.7.7" xarray netcdf4 pandas numpy
  .env in the project folder with CDSAPI_KEY=<personal access token>
  ERA5 licence accepted on the CDS website.
"""
import os

# One BLAS thread: the multi-threaded default ran out of memory on Windows during interpolation
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import calendar
import glob
import sys
import threading
import time
import zipfile
import queue
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "era5_raw"
OUT_CSV = ROOT / "data" / "era5" / "era5_hourly_site_utc.csv"

# Same values as the ML team's notebook (do not change without retraining the models)
SITE_LAT, SITE_LON = -25.24, 130.99
AREA = [SITE_LAT + 0.5, SITE_LON - 0.5, SITE_LAT - 0.5, SITE_LON + 0.5]  # N, W, S, E
FIRST_MONTH, LAST_MONTH = "2016-04", "2026-02"
WORKERS = 4

ERA5_VARS = {
    "surface_solar_radiation_downwards": "ssrd",
    "surface_solar_radiation_downward_clear_sky": "ssrdc",
    "total_sky_direct_solar_radiation_at_surface": "fdir",
    "total_cloud_cover": "tcc",
    "low_cloud_cover": "lcc",
    "medium_cloud_cover": "mcc",
    "high_cloud_cover": "hcc",
    "2m_temperature": "t2m",
    "2m_dewpoint_temperature": "d2m",
    "10m_u_component_of_wind": "u10",
    "10m_v_component_of_wind": "v10",
    "surface_pressure": "sp",
    "total_column_water_vapour": "tcwv",
    "total_precipitation": "tp",
}


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def read_key():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("CDSAPI_KEY="):
                return line.split("=", 1)[1].strip()
    key = os.environ.get("CDSAPI_KEY")
    if not key:
        sys.exit("No CDSAPI_KEY in .env or environment")
    return key


def cached(path):
    return path.exists() and path.stat().st_size > 10_000


def request(year, month):
    days = calendar.monthrange(year, month)[1]
    return {
        "product_type": ["reanalysis"],
        "variable": list(ERA5_VARS),
        "year": [str(year)],
        "month": [f"{month:02d}"],
        "day": [f"{d:02d}" for d in range(1, days + 1)],
        "time": [f"{h:02d}:00" for h in range(24)],
        "area": AREA,
        "data_format": "netcdf",
        "download_format": "unarchived",
    }


def download_all():
    import cdsapi

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    months = pd.period_range(FIRST_MONTH, LAST_MONTH, freq="M")
    todo = [(p.year, p.month) for p in months if not cached(RAW_DIR / f"era5_{p.year}_{p.month:02d}.nc")]
    log(f"{len(months)} months in range, {len(months) - len(todo)} cached, {len(todo)} to download")
    if not todo:
        return

    key = read_key()
    tasks = queue.Queue()
    for t in todo:
        tasks.put(t)
    failed, done = [], []
    lock = threading.Lock()

    def worker(wid):
        client = cdsapi.Client(url="https://cds.climate.copernicus.eu/api", key=key, quiet=True, progress=False)
        while True:
            try:
                year, month = tasks.get_nowait()
            except queue.Empty:
                return
            target = RAW_DIR / f"era5_{year}_{month:02d}.nc"
            for attempt in range(1, 5):
                try:
                    log(f"w{wid} {year}-{month:02d}: requesting (attempt {attempt})")
                    client.retrieve("reanalysis-era5-single-levels", request(year, month), str(target))
                    with lock:
                        done.append((year, month))
                        log(f"w{wid} {year}-{month:02d}: saved ({target.stat().st_size / 1e6:.1f} MB) "
                            f"[{len(done)}/{len(todo)}]")
                    break
                except Exception as ex:  # noqa: BLE001 - CDS raises many types
                    err = str(ex)
                    if target.exists():
                        target.unlink()
                    if "licen" in err.lower():
                        log(f"w{wid}: ERA5 licence not accepted for this account; stopping")
                        with lock:
                            failed.append((year, month))
                        return
                    wait = 60 * attempt
                    log(f"w{wid} {year}-{month:02d}: failed ({err[:120]}); retry in {wait}s")
                    time.sleep(wait)
            else:
                with lock:
                    failed.append((year, month))

    threads = [threading.Thread(target=worker, args=(i + 1,), daemon=True) for i in range(WORKERS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    if failed:
        log(f"FAILED months: {sorted(failed)} (re-run the script to retry them)")
    else:
        log("all months downloaded")


def open_point(path):
    """One monthly file (plain .nc or a zip of .nc files) interpolated to the site point."""
    paths = [path]
    if zipfile.is_zipfile(path):
        out = Path(str(path)[:-3] + "_unzipped")
        out.mkdir(exist_ok=True)
        with zipfile.ZipFile(path) as z:
            z.extractall(out)
        paths = sorted(out.glob("*.nc"))
    ds = xr.merge([xr.open_dataset(p) for p in paths], compat="override", join="outer")
    if "valid_time" in ds.coords:
        ds = ds.rename({"valid_time": "time"})
    if "expver" in ds.dims:
        ev = sorted(ds["expver"].values.tolist())
        ds = ds.sel(expver=ev[0]).combine_first(ds.sel(expver=ev[-1]))
    ds = ds.drop_vars(["number", "expver"], errors="ignore").sortby(["latitude", "longitude"])
    pt = ds.interp(latitude=SITE_LAT, longitude=SITE_LON, method="linear")
    df = pt.to_dataframe().drop(columns=["latitude", "longitude"], errors="ignore")
    ds.close()
    return df


def build_csv():
    files = sorted(glob.glob(str(RAW_DIR / "era5_*.nc")))
    if not files:
        sys.exit("No monthly files in data/era5_raw")
    raw = pd.concat([open_point(f) for f in files]).sort_index()
    raw = raw[~raw.index.duplicated(keep="last")]
    missing = [v for v in ERA5_VARS.values() if v not in raw.columns]
    if missing:
        sys.exit(f"Variables missing in the files: {missing}")

    T, Td = raw["t2m"] - 273.15, raw["d2m"] - 273.15
    e = pd.DataFrame(index=raw.index)
    e["era5_ghi"] = (raw["ssrd"] / 3600).clip(lower=0)            # W/m², mean of the hour ending at stamp
    e["era5_ghi_clearsky"] = (raw["ssrdc"] / 3600).clip(lower=0)
    e["era5_dir_horiz"] = (raw["fdir"] / 3600).clip(lower=0)
    e["era5_precip_mm"] = (raw["tp"] * 1000).clip(lower=0)
    e["era5_temp_c"] = T
    e["era5_dewpoint_c"] = Td
    e["era5_rh"] = (100 * np.exp(17.625 * Td / (243.04 + Td)) / np.exp(17.625 * T / (243.04 + T))).clip(0, 100)
    e["era5_wind_u"] = raw["u10"]
    e["era5_wind_v"] = raw["v10"]
    e["era5_wind_speed"] = np.hypot(raw["u10"], raw["v10"])
    e["era5_pressure_hpa"] = raw["sp"] / 100
    e["era5_tcc"] = raw["tcc"]
    e["era5_lcc"] = raw["lcc"]
    e["era5_mcc"] = raw["mcc"]
    e["era5_hcc"] = raw["hcc"]
    e["era5_tcwv"] = raw["tcwv"]
    e.index.name = "time"

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    e.to_csv(OUT_CSV)
    full = pd.date_range(e.index.min(), e.index.max(), freq="h")
    log(f"saved {OUT_CSV} {e.shape}, {e.index.min()} -> {e.index.max()} UTC, "
        f"missing hours inside range: {len(full.difference(e.index))}")


if __name__ == "__main__":
    if "--build" not in sys.argv:
        download_all()
    build_csv()
