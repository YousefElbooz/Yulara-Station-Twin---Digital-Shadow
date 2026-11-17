// Types and fetch helpers for the twin API (docs/api.md). The site never computes plant physics itself:
// every number it shows or animates comes from one of these endpoints.
import { useCallback, useEffect, useRef, useState } from 'react'

export type Status = 'night' | 'offline' | 'outage' | 'limited' | 'healthy' | string

export interface Step {
  time_utc: string
  time_local?: string
  measured_kw: number | null
  expected_kw: number | null
  ratio: number | null
  status: Status
  ghi_wm2: number | null
  poa_wm2: number | null
  t_air_c: number | null
  t_cell_c: number | null
  wind_ms: number | null
  wind_dir_deg: number | null
  equipment_temp_c: number | null
  sun_elevation_deg: number | null
  src_weather: string | null
  models: Record<string, number | null>
}

export interface Alarm {
  id: number
  type: string
  severity: 'critical' | 'warning' | 'info' | string
  confidence: string
  start_utc: string
  end_utc: string | null
  start_local: string
  end_local?: string | null
  is_open: number
  message: string
  recommendation: string
}

export interface Now {
  time_utc: string
  time_local: string
  step: Step
  today: { measured_kwh: number; expected_kwh: number }
  open_alarms: Alarm[]
  meta: { mode: string; source: string; calibration: string; started_local: string; speed_factor?: number } | null
}

export interface Scene {
  time_local: string
  sun: { elevation_deg: number; azimuth_deg: number }
  weather: { ghi_wm2: number | null; poa_wm2: number | null; t_air_c: number | null; wind_ms: number | null; wind_from_deg: number | null; source: string | null; rain_mm_h?: number | null; cloud_cover?: number | null }
  panels: { t_cell_c: number | null; heat_loss_pct: number; dust_index: number | null; dust_confidence: string }
  power: { measured_kw: number | null; expected_kw: number | null; held_back_kw: number; status: Status }
  equipment: { temp_c: number | null }
  alarms: string[]
  layout: { rows: number; modules: number; tilt_deg: number; azimuth_deg: number; inverters: number; inverters_calculated: boolean }
}

export interface Health { api: string; twin: string; error: string | null; last_step_local: string | null }

export interface Score { n: number; rmse: number; mae: number; bias: number; nrmse: number }
export interface ModelInfo {
  key: string
  name: string
  track: 'day-ahead' | 'nowcast' | 'physics'
  test_rmse_kw_training_split?: number | null
  r2_training_split?: number | null
  y2025?: { all_daylight: Score; unlimited: Score } | null
}

export interface Day {
  date: string
  measured_kwh: number | null
  expected_kwh: number | null
  pr_unlimited: number | null
  pr_smooth: number | null
  soiling_index: number | null
  limit_loss_kwh: number | null
  outage_loss_kwh: number | null
  health_loss_kwh: number | null
  source: 'twin' | 'history'
}

export interface YearSplit { year: number; expected: number; measured: number; health_loss: number; limit_loss: number; outage_loss: number; pr: number | null }

export interface WhatIfReq {
  date: string
  temp_delta_c: number
  soiling_pct: number
  tilt_deg?: number | null
  azimuth_deg?: number | null
  ageing_years: number
}
export interface WhatIfRes {
  energy_kwh: { measured: number; baseline: number; scenario: number }
  points: { time_local: string; measured_kw: number | null; baseline_kw: number; scenario_kw: number; t_cell_baseline_c: number; t_cell_scenario_c: number }[]
}

export async function getJSON<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, init)
  if (!r.ok) {
    let detail = r.statusText
    try { detail = (await r.json()).detail ?? detail } catch { /* not JSON */ }
    throw new Error(`${r.status} ${detail}`)
  }
  return r.json() as Promise<T>
}

/** Poll an endpoint every `ms` milliseconds. Keeps the last good value when a request fails. */
export function usePoll<T>(path: string | null, ms: number) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const alive = useRef(true)
  const load = useCallback(async () => {
    if (!path) return
    try {
      const d = await getJSON<T>(path)
      if (alive.current) { setData(d); setError(null) }
    } catch (e) {
      if (alive.current) setError((e as Error).message)
    }
  }, [path])
  useEffect(() => {
    alive.current = true
    load()
    const id = ms > 0 ? setInterval(load, ms) : undefined
    return () => { alive.current = false; if (id) clearInterval(id) }
  }, [load, ms])
  return { data, error, reload: load }
}

// ---- formatting (no maths about the plant here, only display)
export const fmt = (v: number | null | undefined, d = 0) =>
  v === null || v === undefined || Number.isNaN(v) ? '—' : v.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d })

/** Local Yulara wall-clock from an ISO string that already carries +09:30. */
export const localClock = (iso?: string | null) => (iso ? iso.slice(11, 16) : '—')
export const localDate = (iso?: string | null) => (iso ? iso.slice(0, 10) : '—')

export const STATUS_LABEL: Record<string, string> = {
  night: 'Night',
  healthy: 'Following the sun',
  limited: 'Output held back',
  outage: 'Outage',
  offline: 'No data',
  weather_only: 'Live weather · expected only',
}

export const ALARM_LABEL: Record<string, string> = {
  OFFLINE: 'No data from plant',
  OUTAGE: 'Plant not producing',
  WEATHER_SENSORS_OFF: 'Weather sensors off',
  EQUIPMENT_HOT: 'Equipment hot',
  FAULT: 'Possible fault',
  SOILING: 'Dust build-up',
}

export const MODEL_LABEL: Record<string, string> = {
  ridge: 'Ridge',
  random_forest: 'Random forest',
  xgboost: 'XGBoost',
  lightgbm: 'LightGBM',
  pinn_dayahead: 'DP-PINN day-ahead',
  lightgbm_nowcast: 'LightGBM nowcast',
  pinn_nowcast: 'DP-PINN nowcast',
  stacking: 'Stacking',
}
