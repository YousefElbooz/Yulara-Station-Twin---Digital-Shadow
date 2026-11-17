import { Fragment, Suspense, lazy, useEffect, useState } from 'react'
import type { Health, Now, Scene, Step } from './api'
import { ALARM_LABEL, MODEL_LABEL, STATUS_LABEL, fmt, localClock, localDate, usePoll } from './api'
import { AlarmsTab, HealthTab, ModelsTab, StationTab, TodayTab, WhatIfTab } from './panels'
import Settings from './Settings'
import type { TwinConfig } from './Settings'
import type { View } from './scene/Station'

const Station = lazy(() => import('./scene/Station'))

const TABS = ['Today', 'Models', 'Health', 'Alarms', 'What-if', 'Station'] as const
type Tab = (typeof TABS)[number]

const COMPASS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
const compass = (deg?: number | null) => (deg == null ? '—' : COMPASS[Math.round(deg / 45) % 8])

export default function App() {
  const [fast, setFast] = useState(false) // demo profile: the twin runs faster than real time, so poll faster
  const { data: now, error: nowErr, reload: reloadNow } = usePoll<Now>('/api/now', fast ? 2000 : 5000)
  const { data: scene, reload: reloadScene } = usePoll<Scene>('/api/scene', fast ? 2000 : 5000)
  const { data: health, reload: reloadHealth } = usePoll<Health & { config?: TwinConfig }>('/api/health', 10000)
  const { data: series, reload: reloadSeries } = usePoll<{ points: Step[] }>('/api/series?hours=24', fast ? 8000 : 60000)
  const onApplied = () => { reloadNow(); reloadScene(); reloadHealth(); reloadSeries() }
  const conf = health?.config ?? null
  const speed = now?.meta?.mode === 'speed' ? (now.meta.speed_factor ?? 0) : 0
  useEffect(() => setFast(speed > 0), [speed])
  const [view, setView] = useState<View>('overview')
  const [overlay, setOverlay] = useState<boolean>(() => { try { return localStorage.getItem('twin.overlay') !== 'off' } catch { return true } })
  useEffect(() => { try { localStorage.setItem('twin.overlay', overlay ? 'on' : 'off') } catch { /* private mode */ } }, [overlay])
  const [fx, setFx] = useState<boolean>(() => { try { return localStorage.getItem('twin.fx') !== 'off' } catch { return true } })
  useEffect(() => { try { localStorage.setItem('twin.fx', fx ? 'on' : 'off') } catch { /* private mode */ } }, [fx])
  const [tab, setTab] = useState<Tab>(() => {
    try { return (localStorage.getItem('twin.tab') as Tab) || 'Today' } catch { return 'Today' }
  })
  useEffect(() => { try { localStorage.setItem('twin.tab', tab) } catch { /* private mode */ } }, [tab])

  const step = now?.step
  const status = step?.status ?? 'offline'
  const measured = step?.measured_kw != null ? Math.max(0, step.measured_kw) : null
  const expected = step?.expected_kw ?? null
  const heldBack = scene?.power.held_back_kw ?? 0
  const openAlarms = now?.open_alarms ?? []
  const ratingKw = 1050 // AC capacity, calculated (42 × 25 kW)

  return (
    <>
      <header className="top">
        <div className="brand">
          <b>Yulara 1 · Desert Gardens</b>
          <span>Digital shadow · 1,058 kW PV · Northern Territory, AU</span>
        </div>
        <div className="clock">{localClock(now?.time_local)}<small>{localDate(now?.time_local)} · Yulara time</small></div>
        <span className={`pill ${status} live`}>{STATUS_LABEL[status] ?? status}</span>
        {conf?.mode === 'weather' && <span className="pill weather_only live" title="Real time now; weather from Open-Meteo; no plant feed">LIVE WEATHER · Open-Meteo</span>}
        {conf?.mode === 'replay' && conf.start
          ? <span className="pill demo" title="Real station history, replayed from the chosen moment">REPLAY · from {conf.start.replace('T', ' ')} · ×{conf.speed}</span>
          : speed > 0 && <span className="pill demo">REPLAY · ×{speed}</span>}
        <div className="spacer" />
        <Settings config={conf} onApplied={onApplied} />
        <div className="source">
          source: {conf?.mode === 'weather' ? 'Open-Meteo live weather · no plant feed' : `DKASC history, ${conf?.mode === 'replay' ? 'replay' : 'replayed as live'}`}<br />
          twin {health?.twin ?? '…'} · calibration {now?.meta?.calibration ?? '—'} · mode {now?.meta?.mode ?? '—'}
        </div>
      </header>

      {nowErr && !now && (
        <div className="banner">Cannot reach the twin API ({nowErr}). Start it with the <span className="mono">twin-api</span> launch config, then this page reconnects on its own.</div>
      )}

      <main className="main">
        <section className={`stage${overlay ? '' : ' clean'}`} aria-label="3D view of the station">
          <Suspense fallback={<div className="hint">Loading 3D station…</div>}>
            <Station scene={scene} alarms={openAlarms} view={view} fx={fx} />
          </Suspense>
          <div className="views seg" role="radiogroup" aria-label="Camera view">
            {([['overview', 'Overview'], ['ground', 'Eye level'], ['landscape', 'Landscape'], ['top', 'Top']] as [View, string][]).map(([v, l]) => (
              <button key={v} role="radio" aria-checked={view === v} onClick={() => setView(v)}>{l}</button>
            ))}
            <button className="fx" aria-pressed={overlay} title="Show or hide the info boxes and the legend over the 3D view"
              onClick={() => setOverlay((o) => !o)}>{overlay ? 'Hide illustration' : 'Show illustration'}</button>
            <button className="fx" aria-pressed={fx} title="Ambient occlusion, glare and anti-aliasing. Turn off on slow laptops."
              onClick={() => setFx((f) => !f)}>FX {fx ? 'on' : 'off'}</button>
          </div>
          <div className="hud">
            <div className="chip sun">
              <label>Sun</label>
              <div className="v">{fmt(scene?.sun.elevation_deg, 0)}°<small>high · {fmt(scene?.sun.azimuth_deg, 0)}° {compass(scene?.sun.azimuth_deg)}</small></div>
              <div className="sub">on panels {fmt(scene?.weather.poa_wm2, 0)} W/m² · ground {fmt(Math.max(0, scene?.weather.ghi_wm2 ?? 0), 0)}</div>
            </div>
            <div className="chip wind">
              <label>Wind</label>
              <div className="v">
                {fmt(scene?.weather.wind_ms, 1)}<small>m/s from {compass(scene?.weather.wind_from_deg)}</small>{' '}
                <span className="compass" style={{ transform: `rotate(${(scene?.weather.wind_from_deg ?? 0) + 180}deg)` }}>↑</span>
              </div>
              <div className="sub">
                {(scene?.weather.rain_mm_h ?? 0) >= 0.05 ? `rain ${fmt(scene?.weather.rain_mm_h, 1)} mm/h · ` : ''}
                cloud {scene?.weather.cloud_cover != null ? fmt(100 * scene.weather.cloud_cover, 0) + '%' : '—'} · 6× speed
              </div>
            </div>
            <div className="chip heat">
              <label>Panel heat</label>
              <div className="v">{fmt(scene?.panels.t_cell_c, 1)}<small>°C</small></div>
              <div className="sub">heat costs {fmt(scene?.panels.heat_loss_pct, 1)}% of output</div>
            </div>
            <div className="chip dust">
              <label>Dust</label>
              <div className="v">{scene?.panels.dust_index != null ? fmt(100 * (1 - scene.panels.dust_index), 1) : '—'}<small>% loss</small></div>
              <div className="sub">estimate · low confidence</div>
            </div>
          </div>
          <div className="legend">
            <div><i style={{ background: '#5ab0ff' }} />DC flow · strings → inverters</div>
            <div><i style={{ background: 'var(--energy)' }} />AC flow · trenches → switch room · speed follows kW</div>
            <div><i style={{ background: '#ff6b3d' }} />panels redden with cell heat</div>
            <div><i style={{ background: 'var(--dust)' }} />panels brown with dust index</div>
            <div><i style={{ background: '#a3cbdc' }} />wind strokes · direction + speed · trees sway</div>
            <div><i style={{ background: '#d49a62' }} />dust in the air when wind &gt; 5 m/s</div>
            <div><i style={{ background: '#cfdbe6' }} />rain · ERA5 hourly</div>
            <div><i style={{ background: '#ffd9a0' }} />night lights · on after sunset · poles illustrative</div>
            <div style={{ color: 'var(--faint)' }}>row layout from imagery (±5 m) · buildings approx.</div>
          </div>
        </section>

        <aside className="side">
          <div className="card">
            <h3>Power now <em>{localClock(now?.time_local)}</em></h3>
            <div className="big">{fmt(measured, 0)}<small>kW measured</small></div>
            <div className="bar" title="share of the 1,050 kW AC rating (calculated)">
              <div className="m" style={{ width: `${Math.min(100, (100 * (measured ?? 0)) / ratingKw)}%` }} />
              <div className="h" style={{ width: `${Math.min(100, (100 * heldBack) / ratingKw)}%` }} />
            </div>
            <dl className="kv">
              <dt>Expected (physics)</dt><dd>{fmt(expected, 0)} kW</dd>
              <dt>Held back</dt><dd style={{ color: heldBack > 0 ? 'var(--energy)' : undefined }}>{fmt(heldBack, 0)} kW</dd>
              <dt>Today so far</dt><dd>{fmt((now?.today.measured_kwh ?? 0) / 1000, 2)} MWh</dd>
              <dt>Today expected</dt><dd>{fmt((now?.today.expected_kwh ?? 0) / 1000, 2)} MWh</dd>
            </dl>
            {status === 'weather_only' && <p className="note"><b>Live weather mode.</b> Expected power is computed now from Open-Meteo weather.
              No live plant meter is connected yet, so measured power is empty.</p>}
            {status === 'limited' && <p className="note"><b>Output held back.</b> The sun allows more than the plant is giving; most likely limited to the resort's demand.</p>}
          </div>

          <div className="card">
            <h3>Weather <em>{step?.src_weather === 'era5' ? 'ERA5 backup' : 'site sensors'}</em></h3>
            <dl className="kv" style={{ marginTop: 0 }}>
              <dt>Air</dt><dd>{fmt(step?.t_air_c, 1)} °C</dd>
              <dt>Panel cells</dt><dd>{fmt(step?.t_cell_c, 1)} °C</dd>
              <dt>Equipment probe</dt><dd>{fmt(step?.equipment_temp_c, 1)} °C</dd>
              <dt>Wind</dt><dd>{fmt(step?.wind_ms, 1)} m/s {compass(step?.wind_dir_deg)}</dd>
            </dl>
          </div>

          <div className="card">
            <h3>Forecasts for this step <em>kW</em></h3>
            <div className="models-mini">
              {['stacking', 'pinn_nowcast', 'lightgbm_nowcast', 'pinn_dayahead', 'lightgbm'].map((k) => (
                <Fragment key={k}><span>{MODEL_LABEL[k]}</span><span>{fmt(step?.models?.[k], 0)}</span></Fragment>
              ))}
            </div>
          </div>

          <div className="card">
            <h3>Alarms <em>{openAlarms.length} open</em></h3>
            {openAlarms.length === 0 ? <p className="ok">All clear.</p> : (
              <div className="alarm-mini">
                {openAlarms.map((a) => (
                  <div key={a.id} className={`a sev-${a.severity}`}>
                    <b>{ALARM_LABEL[a.type] ?? a.type}</b>
                    <span>{a.recommendation}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </aside>
      </main>

      <section className="tabs-wrap">
        <nav className="tabs" role="tablist">
          {TABS.map((t) => (
            <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}>
              {t}{t === 'Alarms' && openAlarms.length > 0 && <span className="count">{openAlarms.length}</span>}
            </button>
          ))}
        </nav>
        {tab === 'Today' && <TodayTab points={series?.points ?? []} />}
        {tab === 'Models' && <ModelsTab />}
        {tab === 'Health' && <HealthTab />}
        {tab === 'Alarms' && <AlarmsTab />}
        {tab === 'What-if' && <WhatIfTab defaultDate={now ? `${Number(now.time_local.slice(0, 4))}-${now.time_local.slice(5, 10)}` : '2025-07-15'} />}
        {tab === 'Station' && <StationTab />}
      </section>

      <footer className="foot">
        Data: DKA Solar Centre, Yulara 1 – Desert Gardens (history replayed as live). Weather backup: ERA5, Copernicus Climate Change Service.
        Live weather: <a href="https://open-meteo.com/" target="_blank" rel="noreferrer">Open-Meteo.com</a> (CC BY 4.0), model data.
        Inverter count (42) and AC capacity are calculated, not published. Equipment and mast positions are approximate.
      </footer>
    </>
  )
}
