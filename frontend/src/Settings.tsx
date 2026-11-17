// Settings panel: run the twin live (today's time at Yulara) or replay from a chosen moment, at a chosen speed.
// Applying restarts the twin on the server (POST /api/twin/config); the page then follows the new clock.
import { useEffect, useRef, useState } from 'react'
import { getJSON } from './api'

export interface TwinConfig { mode: 'live' | 'replay' | 'weather'; start: string | null; speed: number; applied_at_utc?: string }
interface Limits { first_local: string; last_local: string; models_from_local: string; speeds: number[] }

// Real moments worth showing, all from the station file (local Yulara time)
const PRESETS: { label: string; start: string; speed: number; why: string }[] = [
  { label: 'Real outage', start: '2025-10-04T08:15', speed: 90, why: 'following the sun → held back → zero at 10:40, OUTAGE alarm ~11:10' },
  { label: 'Hottest day 2025', start: '2025-03-01T10:00', speed: 60, why: 'air up to 44.8 °C: watch the panels glow and the heat loss climb' },
  { label: 'Windiest midday 2025', start: '2025-03-24T09:00', speed: 60, why: 'about 5 m/s average 10:00–15:00: wind streaks and blowing sand' },
  { label: 'Rainy morning', start: '2025-03-31T08:30', speed: 60, why: 'wettest ERA5 hours of 2025 (~2 mm/h, 09:30-11:30): rain, grey haze, low sun' },
  { label: 'Winter morning', start: '2025-07-15T06:30', speed: 90, why: 'low sun from the north-east, long shadows between the rows' },
]

export default function Settings({ config, onApplied }: { config: TwinConfig | null; onApplied: () => void }) {
  const [open, setOpen] = useState(false)
  const [limits, setLimits] = useState<Limits | null>(null)
  const [mode, setMode] = useState<'live' | 'replay' | 'weather'>('live')
  const [date, setDate] = useState('2025-10-04')
  const [time, setTime] = useState('08:15')
  const [speed, setSpeed] = useState(90)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const box = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    getJSON<{ config: TwinConfig; limits: Limits }>('/api/twin/config').then((r) => {
      setLimits(r.limits)
      const c = r.config
      if (c?.mode) setMode(c.mode)
      if (c?.mode === 'replay' && c.start) { setDate(c.start.slice(0, 10)); setTime(c.start.slice(11, 16)); setSpeed(c.speed) }
    }).catch((e) => setErr((e as Error).message))
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    const onDown = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false) }
    window.addEventListener('keydown', onKey)
    window.addEventListener('mousedown', onDown)
    return () => { window.removeEventListener('keydown', onKey); window.removeEventListener('mousedown', onDown) }
  }, [open])

  const apply = async (override?: { start: string; speed: number }) => {
    setBusy(true); setErr(null)
    const body = override ? { mode: 'replay', ...override }
      : mode === 'live' ? { mode: 'live' } : mode === 'weather' ? { mode: 'weather' } : { mode: 'replay', start: `${date}T${time}`, speed }
    try {
      await getJSON('/api/twin/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      // wait until the new twin has processed its first steps
      for (let i = 0; i < 60; i++) {
        const h = await getJSON<{ twin: string; error: string | null }>('/api/health')
        if (h.twin === 'running') break
        if (h.twin === 'error') throw new Error(h.error ?? 'twin failed to start')
        await new Promise((r) => setTimeout(r, 1000))
      }
      onApplied()
      setOpen(false)
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }

  const noModels = mode === 'replay' && limits && date < limits.models_from_local
  return (
    <div className="settings" ref={box}>
      <button className="gear" aria-label="Twin settings" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <circle cx="12" cy="12" r="3" />
          <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" />
        </svg>
        <span>{config?.mode === 'replay' ? 'Replay' : config?.mode === 'weather' ? 'Live weather' : 'History now'}</span>
      </button>
      {open && (
        <div className="settings-panel" role="dialog" aria-label="Twin settings">
          <h3>Twin clock</h3>
          <div className="seg" role="radiogroup">
            <button role="radio" aria-checked={mode === 'weather'} onClick={() => setMode('weather')}>Live weather</button>
            <button role="radio" aria-checked={mode === 'live'} onClick={() => setMode('live')}>History now</button>
            <button role="radio" aria-checked={mode === 'replay'} onClick={() => setMode('replay')}>Replay…</button>
          </div>
          {mode === 'weather' ? (
            <p className="note"><b>Real time now</b> at Yulara with <b>live weather from Open-Meteo</b> (model values, updated hourly,
              interpolated to 5 min). The calibrated physics shows what the plant <b>should</b> produce now. No live plant
              power yet (DKASC feed not connected), so measured power and plant alarms are off.</p>
          ) : mode === 'live' ? (
            <p className="note">Today's date and time at Yulara, from the latest year in the station file, at real speed.</p>
          ) : (
            <>
              <div className="row2">
                <label>Date (Yulara)
                  <input type="date" value={date} min={limits?.first_local.slice(0, 10)} max={limits?.last_local.slice(0, 10)} onChange={(e) => setDate(e.target.value)} />
                </label>
                <label>Time
                  <input type="time" value={time} step={300} onChange={(e) => setTime(e.target.value)} />
                </label>
              </div>
              <label className="lbl">Speed</label>
              <div className="seg">
                {(limits?.speeds ?? [1, 30, 90, 300]).map((s) => (
                  <button key={s} aria-checked={speed === s} role="radio" onClick={() => setSpeed(s)}>×{s}</button>
                ))}
              </div>
              <p className="note">×{speed}: one 5-minute step every {(300 / speed).toFixed(speed >= 100 ? 1 : 0)} s · a day in {fmtDur((86400 / speed))}.</p>
              {noModels && <p className="note warn">Before {limits!.models_from_local} the ML forecasts are not available (they were trained on that period). Physics, alarms and the 3D view still work.</p>}
            </>
          )}
          <button className="btn" disabled={busy} onClick={() => apply()} style={{ width: '100%' }}>{busy ? 'Restarting the twin…' : 'Apply'}</button>
          {err && <p className="err">{err}</p>}
          <h3 style={{ marginTop: 20 }}>Real moments</h3>
          <div className="presets">
            {PRESETS.map((p) => (
              <button key={p.label} disabled={busy} onClick={() => apply({ start: p.start, speed: p.speed })}>
                <b>{p.label}</b><span>{p.start.replace('T', ' ')} · ×{p.speed}</span><em>{p.why}</em>
              </button>
            ))}
          </div>
          <p className="note">Applying restarts the twin from that moment: steps, alarms and today's totals start fresh.</p>
        </div>
      )}
    </div>
  )
}

function fmtDur(s: number) {
  if (s >= 3600) return `${(s / 3600).toFixed(s >= 36000 ? 0 : 1)} h`
  if (s >= 60) return `${Math.round(s / 60)} min`
  return `${Math.round(s)} s`
}
