"""
Physics model of Yulara Desert Gardens: what the plant SHOULD produce for the weather it had.

Chain (all standard pvlib models, chosen in config/physics.yaml):
  sun position -> GHI split into direct/diffuse (Erbs) -> irradiance on the 15 deg north-facing
  plane (Perez) -> reflection loss on the direct part (physical IAM) -> cell temperature (SAPM,
  open rack) -> DC power (PVWatts, gamma from the datasheet) -> DC losses -> inverter (PVWatts,
  AC limit = calculated inverter capacity).

The same function serves the history run (scripts/simulate_physics.py) and, later, the live twin.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pvlib


def simulate(weather: pd.DataFrame, station: dict, physics: dict, calibration: dict | None = None) -> pd.DataFrame:
    """
    weather: index = time_utc (tz-aware, label per physics['timestamp_label']),
             columns ghi_wm2, t_air_c, wind_ms (canonical names, docs/data_contract.md)
    calibration: optional overrides {pdc0_kw, gamma_pdc_per_c, dc_loss_fraction, ac_limit_kw}
    Returns a frame on the same index with the intermediate and final quantities.
    """
    loc, arr, mod, inv = station["location"], station["array"], station["module"], station["inverter"]
    cal = calibration or {}

    # sun position at the middle of each interval
    shift = pd.Timedelta(minutes=physics["interval_minutes"] / 2)
    if physics["timestamp_label"] == "end":
        t_sun = weather.index - shift
    elif physics["timestamp_label"] == "start":
        t_sun = weather.index + shift
    else:
        t_sun = weather.index
    sp = pvlib.solarposition.get_solarposition(t_sun, loc["latitude"], loc["longitude"], altitude=loc["altitude_m"])
    sp.index = weather.index
    zen, app_zen, azi = sp["zenith"], sp["apparent_zenith"], sp["azimuth"]

    ghi = weather["ghi_wm2"].clip(lower=0)
    sun_up = app_zen < 90
    ghi = ghi.where(sun_up, 0.0)

    # 1. GHI -> DNI + DHI
    if physics["decomposition"] != "erbs":
        raise ValueError("only 'erbs' decomposition is implemented")
    sp_doy = pd.DatetimeIndex(t_sun).dayofyear
    dec = pvlib.irradiance.erbs(ghi, zen, sp_doy)
    dni = pd.Series(np.asarray(dec["dni"], dtype="float64"), index=weather.index).fillna(0.0)
    dhi = pd.Series(np.asarray(dec["dhi"], dtype="float64"), index=weather.index).fillna(0.0)
    # keep missing GHI missing (Erbs turns it into 0 after fillna)
    dni = dni.where(ghi.notna())
    dhi = dhi.where(ghi.notna())

    # 2. plane of array
    dni_extra = pvlib.irradiance.get_extra_radiation(pd.DatetimeIndex(t_sun))
    dni_extra = pd.Series(np.asarray(dni_extra), index=weather.index)
    airmass = pvlib.atmosphere.get_relative_airmass(app_zen)
    poa = pvlib.irradiance.get_total_irradiance(
        arr["tilt_deg"], arr["azimuth_deg"], app_zen, azi, dni, ghi, dhi,
        dni_extra=dni_extra, airmass=airmass, albedo=physics["albedo"], model=physics["transposition"],
    ).fillna(0.0)

    # 3. reflection loss on the direct beam
    aoi = pvlib.irradiance.aoi(arr["tilt_deg"], arr["azimuth_deg"], app_zen, azi)
    iam = pvlib.iam.physical(aoi).fillna(0.0) if physics["iam"] == "physical" else 1.0
    poa_eff = (poa["poa_direct"] * iam + poa["poa_diffuse"]).clip(lower=0)

    # 4. cell temperature
    tp = pvlib.temperature.TEMPERATURE_MODEL_PARAMETERS["sapm"]["open_rack_glass_polymer"]
    t_cell = pvlib.temperature.sapm_cell(poa["poa_global"], weather["t_air_c"], weather["wind_ms"].fillna(1.0), **tp)

    # 5. DC power, losses, inverter
    pdc0_w = 1000 * cal.get("pdc0_kw", arr["dc_capacity_kw"])
    gamma = cal.get("gamma_pdc_per_c", mod["gamma_pdc_per_c"])
    loss = cal.get("dc_loss_fraction", physics["dc_loss_fraction"])
    ac_limit_w = 1000 * cal.get("ac_limit_kw", inv["ac_capacity_kw"])
    eta = inv["euro_efficiency"]

    p_dc = pvlib.pvsystem.pvwatts_dc(poa_eff, t_cell, pdc0=pdc0_w, gamma_pdc=gamma) * (1 - loss)
    p_ac = pvlib.inverter.pvwatts(p_dc, pdc0=ac_limit_w / eta, eta_inv_nom=eta)
    p_ac = p_ac.clip(lower=0).where(sun_up, 0.0)

    return pd.DataFrame({
        "sun_zenith_deg": zen.astype("float32"),
        "sun_azimuth_deg": azi.astype("float32"),
        "dni_wm2": dni.astype("float32"),
        "dhi_wm2": dhi.astype("float32"),
        "poa_global_wm2": poa["poa_global"].astype("float32"),
        "poa_effective_wm2": poa_eff.astype("float32"),
        "aoi_deg": aoi.astype("float32"),
        "t_cell_c": t_cell.astype("float32"),
        "p_dc_kw": (p_dc / 1000).astype("float32"),
        "p_expected_kw": (p_ac / 1000).astype("float32"),
        "ghi_clearsky_wm2": pvlib.clearsky.haurwitz(app_zen)["ghi"].fillna(0).astype("float32"),
    }, index=weather.index)
