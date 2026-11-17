// The tabs under the 3D station. Every chart reads an API endpoint; nothing here models the plant.
import { useMemo, useState } from 'react'
import type { Alarm, Day, ModelInfo, Step, WhatIfReq, WhatIfRes, YearSplit } from './api'
import { ALARM_LABEL, MODEL_LABEL, fmt, getJSON, localClock, usePoll } from './api'
import Plot, { C } from './Plot'

// ------------------------------------------------------------------ Today
export function TodayTab({ points }: { points: Step[] }) {
  const [show, setShow] = useState<string[]>(['stacking', 'pinn_dayahead'])
  const x = points.map((p) => p.time_local!.slice(0, 19))
  const data = useMemo<Plotly.Data[]>(() => {
    const d: Plotly.Data[] = [
      { x, y: points.map((p) => p.expected_kw), name: 'Expected (calibrated physics)', type: 'scatter', mode: 'lines',
        line: { color: C.physics, width: 2, dash: 'dot' } },
      { x, y: points.map((p) => (p.measured_kw != null ? Math.max(0, p.measured_kw) : null)), name: 'Measured', type: 'scatter', mode: 'lines',
        line: { color: C.measured, width: 2.5 }, fill: 'tozeroy', fillcolor: 'rgba(48,213,200,0.10)' },
    ]
    const palette = ['#5ab0ff', '#a78bfa', '#7dd3fc', '#f472b6']
    show.forEach((k, i) => d.push({ x, y: points.map((p) => p.models?.[k] ?? null), name: MODEL_LABEL[k], type: 'scatter', mode: 'lines',
      line: { color: palette[i % palette.length], width: 1.5 } }))
    return d
  }, [points, show]) // eslint-disable-line react-hooks/exhaustive-deps
  const weather = useMemo<Plotly.Data[]>(() => [
    { x, y: points.map((p) => p.ghi_wm2 != null ? Math.max(0, p.ghi_wm2) : null), name: 'Sunlight on ground (GHI, W/m²)', type: 'scatter', mode: 'lines', line: { color: C.sun, width: 1.5 } },
    { x, y: points.map((p) => p.t_cell_c), name: 'Panel temperature (°C)', type: 'scatter', mode: 'lines', yaxis: 'y2', line: { color: '#ff8a5c', width: 1.5 } },
    { x, y: points.map((p) => p.wind_ms), name: 'Wind (m/s)', type: 'scatter', mode: 'lines', yaxis: 'y2', line: { color: '#cfe8ff', width: 1, dash: 'dot' } },
  ], [points]) // eslint-disable-line react-hooks/exhaustive-deps
  const toggle = (k: string) => setShow((s) => (s.includes(k) ? s.filter((v) => v !== k) : [...s, k].slice(-4)))
  return (
    <div className="grid-2">
      <div className="card">
        <h3>Power, last 24 h <em>kW · 5-minute steps · Yulara time</em></h3>
        <Plot data={data} height={340} layout={{ yaxis: { title: { text: 'kW' }, gridcolor: C.grid, rangemode: 'tozero' } }} />
        <p className="note">The gap between the dotted line and the measured area is output the plant could have made but held back (or lost to an outage).</p>
      </div>
      <div className="card">
        <h3>Compare forecasts</h3>
        <p className="note" style={{ marginTop: 0, marginBottom: 12 }}>Pick up to four models to draw on the chart.</p>
        <div className="form">
          {Object.entries(MODEL_LABEL).map(([k, n]) => (
            <label key={k} style={{ display: 'flex', gap: 10, alignItems: 'center', cursor: 'pointer' }}>
              <input type="checkbox" checked={show.includes(k)} onChange={() => toggle(k)} style={{ accentColor: C.model }} />
              <span style={{ color: 'var(--ink)' }}>{n}</span>
              <span className={`tag-inline ${k.includes('nowcast') || k === 'stacking' ? 'nowcast' : ''}`} style={{ marginLeft: 'auto' }}>
                {k.includes('nowcast') || k === 'stacking' ? 'nowcast' : 'day-ahead'}
              </span>
            </label>
          ))}
        </div>
      </div>
      <div className="card" style={{ gridColumn: '1 / -1' }}>
        <h3>Weather the twin is using</h3>
        <Plot data={weather} height={240} layout={{ yaxis: { title: { text: 'W/m²' }, gridcolor: C.grid }, yaxis2: { overlaying: 'y', side: 'right', title: { text: '°C · m/s' }, showgrid: false } }} />
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ Models
export function ModelsTab() {
  const { data } = usePoll<{ models: ModelInfo[]; split: Record<string, string> }>('/api/models', 0)
  const [scoring, setScoring] = useState<'unlimited' | 'all_daylight'>('unlimited')
  if (!data) return <p className="dim">Loading models…</p>
  const rows = data.models.filter((m) => m.y2025).sort((a, b) => a.y2025![scoring].rmse - b.y2025![scoring].rmse)
  const best = rows[0]?.key
  const colour = (m: ModelInfo) => (m.track === 'physics' ? C.physics : m.track === 'nowcast' ? C.model : '#7c8aa8')
  const chart: Plotly.Data[] = [{
    type: 'bar', orientation: 'h',
    y: rows.map((m) => m.name).reverse(), x: rows.map((m) => m.y2025![scoring].rmse).reverse(),
    marker: { color: rows.map(colour).reverse() },
    text: rows.map((m) => fmt(m.y2025![scoring].rmse, 1)).reverse(), textposition: 'outside', cliponaxis: false,
    hovertemplate: '%{y}: %{x:.1f} kW<extra></extra>',
  }]
  return (
    <div>
      <p className="lead">
        Every model scored on <b>2025</b>, a year none of them trained on. <b>Unlimited moments</b> are the times the plant was
        free to follow the sun (sun above 10°, physics expects 50–300 kW). <b>All daylight</b> includes the hours the plant held its output back,
        which the physics does not know about, and the nowcast models copy from the last hour.
      </p>
      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        <button className={scoring === 'unlimited' ? 'btn' : 'btn ghost'} onClick={() => setScoring('unlimited')}>Unlimited moments</button>
        <button className={scoring === 'all_daylight' ? 'btn' : 'btn ghost'} onClick={() => setScoring('all_daylight')}>All daylight</button>
      </div>
      <div className="grid-2">
        <div className="card">
          <h3>Error, 2025 <em>RMSE kW · lower is better</em></h3>
          <Plot data={chart} height={360} layout={{ margin: { l: 170, r: 50, t: 8, b: 36 }, hovermode: 'closest', xaxis: { title: { text: 'kW' }, gridcolor: C.grid } }} />
        </div>
        <div className="card">
          <h3>Read it like this</h3>
          <p className="note" style={{ marginTop: 0 }}><span style={{ color: C.physics }}>■</span> <b>Physics</b>: weather only. Best when the plant is free; blind to output limiting.</p>
          <p className="note"><span style={{ color: C.model }}>■</span> <b>Nowcast</b>: uses the plant's power from the last hour, so it learns the limiting.</p>
          <p className="note"><span style={{ color: '#7c8aa8' }}>■</span> <b>Day-ahead</b>: weather + calendar only, no recent power.</p>
          <p className="note">Training split: {Object.entries(data.split ?? {}).map(([k, v]) => `${k} ${v}`).join(' · ')}</p>
        </div>
      </div>
      <div className="card" style={{ marginTop: 16, overflowX: 'auto' }}>
        <table className="t">
          <thead><tr><th>Model</th><th>Uses</th><th className="n">2025 RMSE</th><th className="n">Bias</th><th className="n">nRMSE</th><th className="n">Test RMSE (training split)</th></tr></thead>
          <tbody>
            {rows.map((m) => (
              <tr key={m.key} className={m.key === best ? 'best' : ''}>
                <td>{m.name}</td>
                <td><span className={`tag-inline ${m.track}`}>{m.track}</span></td>
                <td className="n">{fmt(m.y2025![scoring].rmse, 1)} kW</td>
                <td className="n">{fmt(m.y2025![scoring].bias, 1)}</td>
                <td className="n">{fmt(m.y2025![scoring].nrmse, 2)}%</td>
                <td className="n">{m.test_rmse_kw_training_split != null ? `${fmt(m.test_rmse_kw_training_split, 1)} kW` : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ Health
export function HealthTab() {
  const { data: d } = usePoll<{ days: Day[] }>('/api/days?limit=60', 60000)
  const { data: h } = usePoll<{ years: YearSplit[] }>('/api/health-history', 0)
  const days = d?.days ?? []
  const x = days.map((r) => r.date)
  const daily: Plotly.Data[] = [
    { type: 'bar', x, y: days.map((r) => r.measured_kwh != null ? r.measured_kwh / 1000 : null), name: 'Delivered', marker: { color: C.measured } },
    { type: 'bar', x, y: days.map((r) => r.limit_loss_kwh != null ? Math.max(0, r.limit_loss_kwh) / 1000 : null), name: 'Held back', marker: { color: 'rgba(255,176,32,0.55)' } },
    { type: 'bar', x, y: days.map((r) => r.outage_loss_kwh ? r.outage_loss_kwh / 1000 : null), name: 'Lost to outage', marker: { color: C.alarm } },
    { type: 'scatter', mode: 'lines', x, y: days.map((r) => r.soiling_index), name: 'Dust index (1 = clean)', yaxis: 'y2', line: { color: C.dust, width: 2 } },
    { type: 'scatter', mode: 'lines', x, y: days.map((r) => r.pr_smooth), name: 'Performance (7-day)', yaxis: 'y2', line: { color: '#e6ecf5', width: 1.5, dash: 'dot' } },
  ]
  const years = h?.years ?? []
  const yearly: Plotly.Data[] = [
    { type: 'bar', x: years.map((y) => y.year), y: years.map((y) => y.measured), name: 'Delivered', marker: { color: C.measured } },
    { type: 'bar', x: years.map((y) => y.year), y: years.map((y) => Math.max(0, y.limit_loss)), name: 'Held back', marker: { color: 'rgba(255,176,32,0.55)' } },
    { type: 'bar', x: years.map((y) => y.year), y: years.map((y) => y.outage_loss), name: 'Lost to outage', marker: { color: C.alarm } },
  ]
  return (
    <div className="grid-eq">
      <div className="card" style={{ gridColumn: '1 / -1' }}>
        <h3>Last 60 days <em>MWh per day · right axis: ratios</em></h3>
        <Plot data={daily} height={320} layout={{ barmode: 'stack', yaxis: { title: { text: 'MWh' }, gridcolor: C.grid }, yaxis2: { overlaying: 'y', side: 'right', range: [0.8, 1.1], showgrid: false } }} />
        <p className="note">Days before the twin started come from the 2016–2026 history (step 5); days after come from the running twin. The dust index is a <b>low-confidence</b> estimate: no soiling sensor at the site.</p>
      </div>
      <div className="card" style={{ gridColumn: '1 / -1' }}>
        <h3>Where the energy went, per year <em>MWh</em></h3>
        <Plot data={yearly} height={300} layout={{ barmode: 'stack', hovermode: 'x unified', yaxis: { title: { text: 'MWh' }, gridcolor: C.grid } }} />
        <p className="note">"Held back" is the gap between the calibrated physics and the meter on days the plant was running. The likely cause is output limiting to match the resort's demand; that is a strong hypothesis, not confirmed by the operator.</p>
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ Alarms
const SEV_C: Record<string, string> = { critical: 'var(--alarm)', warning: 'var(--energy)', info: 'var(--model)' }
export function AlarmsTab() {
  const { data } = usePoll<{ alarms: Alarm[] }>('/api/alarms?limit=200', 10000)
  const list = data?.alarms ?? []
  if (!list.length) return <p className="ok">No alarms since the twin started.</p>
  return (
    <div className="card">
      {list.map((a) => (
        <div key={a.id} className="alarm-row">
          <span className="sev" style={{ color: SEV_C[a.severity] }}>{a.is_open ? '● ' : '○ '}{a.severity}</span>
          <div>
            <b>{ALARM_LABEL[a.type] ?? a.type}</b>
            <p>{a.message}</p>
            <p><span style={{ color: 'var(--ink)' }}>Do:</span> {a.recommendation}</p>
          </div>
          <div className="when">
            {a.start_local.slice(0, 10)} {localClock(a.start_local)}<br />
            {a.is_open ? <span style={{ color: SEV_C[a.severity] }}>open</span> : <>→ {a.end_local ? `${a.end_local.slice(0, 10)} ${localClock(a.end_local)}` : ''}</>}
          </div>
        </div>
      ))}
    </div>
  )
}

// ------------------------------------------------------------------ What-if
export function WhatIfTab({ defaultDate }: { defaultDate: string }) {
  const [req, setReq] = useState<WhatIfReq>({ date: defaultDate, temp_delta_c: 5, soiling_pct: 5, tilt_deg: 15, ageing_years: 0 })
  const [res, setRes] = useState<WhatIfRes | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const run = async () => {
    setBusy(true); setErr(null)
    try {
      setRes(await getJSON<WhatIfRes>('/api/whatif', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...req, tilt_deg: req.tilt_deg === 15 ? null : req.tilt_deg }) }))
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  const set = (k: keyof WhatIfReq) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setReq((r) => ({ ...r, [k]: k === 'date' ? e.target.value : Number(e.target.value) }))
  const pct = res ? (100 * (res.energy_kwh.scenario - res.energy_kwh.baseline)) / res.energy_kwh.baseline : 0
  const x = res?.points.map((p) => p.time_local.slice(0, 19)) ?? []
  return (
    <div className="grid-2">
      <div className="card">
        <h3>The same real day, under different conditions <em>calibrated physics</em></h3>
        {res ? (
          <Plot height={340} data={[
            { x, y: res.points.map((p) => p.baseline_kw), name: 'As it was (physics)', type: 'scatter', mode: 'lines', line: { color: C.physics, width: 2, dash: 'dot' } },
            { x, y: res.points.map((p) => p.scenario_kw), name: 'What-if', type: 'scatter', mode: 'lines', line: { color: C.model, width: 2.5 }, fill: 'tonexty', fillcolor: pct < 0 ? 'rgba(255,92,122,0.12)' : 'rgba(48,213,200,0.12)' },
            { x, y: res.points.map((p) => (p.measured_kw != null ? Math.max(0, p.measured_kw) : null)), name: 'Measured that day', type: 'scatter', mode: 'lines', line: { color: C.measured, width: 1 } },
          ]} layout={{ yaxis: { title: { text: 'kW' }, gridcolor: C.grid, rangemode: 'tozero' } }} />
        ) : <p className="dim" style={{ minHeight: 340, display: 'grid', placeItems: 'center' }}>Set the conditions and press Run.</p>}
        {res && (
          <div style={{ display: 'flex', gap: 32, alignItems: 'baseline', flexWrap: 'wrap' }}>
            <div><div className="dim">Physics, as it was</div><div className="num" style={{ fontSize: 20 }}>{fmt(res.energy_kwh.baseline)} kWh</div></div>
            <div><div className="dim">What-if</div><div className="num" style={{ fontSize: 20 }}>{fmt(res.energy_kwh.scenario)} kWh</div></div>
            <div className={`delta ${pct >= 0 ? 'up' : 'down'}`}>{pct >= 0 ? '+' : ''}{fmt(pct, 1)}%</div>
            <div><div className="dim">Meter that day</div><div className="num" style={{ fontSize: 20, color: 'var(--live)' }}>{fmt(res.energy_kwh.measured)} kWh</div></div>
          </div>
        )}
      </div>
      <div className="card">
        <h3>Conditions</h3>
        <div className="form">
          <label>Day (Yulara) <input type="date" min="2016-04-01" max="2026-02-19" value={req.date} onChange={set('date')} /></label>
          <label>Air temperature <b>{req.temp_delta_c > 0 ? '+' : ''}{req.temp_delta_c} °C</b>
            <input type="range" min={-10} max={10} step={1} value={req.temp_delta_c} onChange={set('temp_delta_c')} /></label>
          <label>Dust on the panels <b>{req.soiling_pct}% loss</b>
            <input type="range" min={0} max={30} step={1} value={req.soiling_pct} onChange={set('soiling_pct')} /></label>
          <label>Panel tilt <b>{req.tilt_deg}°{req.tilt_deg === 15 ? ' (real)' : ''}</b>
            <input type="range" min={0} max={45} step={1} value={req.tilt_deg ?? 15} onChange={set('tilt_deg')} /></label>
          <label>Extra ageing <b>{req.ageing_years} years</b>
            <input type="range" min={0} max={20} step={1} value={req.ageing_years} onChange={set('ageing_years')} /></label>
          <button className="btn" onClick={run} disabled={busy}>{busy ? 'Running…' : 'Run'}</button>
          {err && <p className="err">{err}</p>}
          <p className="note">Uses the real weather of that day, then changes only what you set. Ageing uses the 0.95% per year trend found in step 4.</p>
        </div>
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ Station
interface StationInfo {
  name: string
  location: { latitude: number; longitude: number; altitude_m: number; timezone: string }
  array: { modules: number; module_model: string; dc_capacity_kw: number; tilt_deg: number; azimuth_deg: number; rows: number; modules_deep_portrait: number; row_pitch_m: number; mounting: string }
  module: { efficiency: number; gamma_pdc_per_c: number; noct_c: number; length_m: number; width_m: number; module_stc_w?: number }
  inverter: { model: string; ac_rating_kw_each: number; count: number; ac_capacity_kw: number; euro_efficiency: number }
  calibration: { version: string; fitted_on_years: number[]; dc_loss_fraction: number; test_year: number; test_unlimited_rmse_kw: number }
}
export function StationTab() {
  const { data: s } = usePoll<StationInfo>('/api/station', 0)
  if (!s) return <p className="dim">Loading…</p>
  const Calc = () => <span className="tag-inline calc">calculated</span>
  const rows: [string, React.ReactNode, React.ReactNode?][] = [
    ['Location', `${s.location.latitude}°, ${s.location.longitude}° · ${s.location.altitude_m} m`, 'Yulara, Northern Territory'],
    ['Panels', `${fmt(s.array.modules)} × ${s.array.module_model}`, `${fmt(s.array.dc_capacity_kw, 1)} kW DC`],
    ['Layout', `${s.array.rows} east–west rows, ${s.array.modules_deep_portrait} portrait deep`, <Calc />],
    ['Tilt / facing', `${s.array.tilt_deg}° · north`, s.array.mounting],
    ['Row spacing', `≈ ${s.array.row_pitch_m} m`, 'from aerial imagery'],
    ['Panel efficiency', `${fmt(100 * s.module.efficiency, 2)}%`, 'datasheet'],
    ['Heat loss per °C', `${fmt(100 * s.module.gamma_pdc_per_c, 2)}% / °C`, 'datasheet'],
    ['Inverter model', s.inverter.model, `${s.inverter.ac_rating_kw_each} kW each`],
    ['Inverter count', `${s.inverter.count}`, <Calc />],
    ['AC capacity', `${fmt(s.inverter.ac_capacity_kw)} kW`, <Calc />],
    ['Calibration', `${s.calibration.version} · fitted ${s.calibration.fitted_on_years.join('–')}`, `DC losses ${fmt(100 * s.calibration.dc_loss_fraction, 1)}%`],
    ['Calibration test', `${s.calibration.test_year}: ${fmt(s.calibration.test_unlimited_rmse_kw, 1)} kW RMSE`, 'unlimited moments'],
  ]
  return (
    <div className="grid-2">
      <div className="card">
        <h3>{s.name} <em>DKA Solar Centre</em></h3>
        <table className="t"><tbody>
          {rows.map(([k, v, n]) => <tr key={k}><td className="dim">{k}</td><td>{v}</td><td style={{ textAlign: 'right' }}>{n}</td></tr>)}
        </tbody></table>
      </div>
      <div className="card">
        <h3>What is real and what is not</h3>
        <p className="note" style={{ marginTop: 0 }}><b>42 inverters is calculated</b>, not published: 1,058 kW DC ÷ 25 kW per inverter. The real number and their positions are unknown.</p>
        <p className="note">The <b>row layout</b> comes from aerial imagery and OpenStreetMap (lengths ± 5 m). The equipment building and weather mast positions in the 3D view are <b>approximate</b>.</p>
        <p className="note">This is a <b>digital shadow</b>: data flows one way, from the plant's history to the model. It recommends; a person decides.</p>
        <p className="note">Data: DKA Solar Centre (dkasolarcentre.com.au), replayed from its history. Weather backup: ERA5 (Copernicus).</p>
      </div>
    </div>
  )
}
