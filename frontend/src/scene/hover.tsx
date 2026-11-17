// Hover-to-explain: objects in the 3D view carry hover handlers (hov('key')); one tag follows the hovered
// object and says what it is, with live numbers where we have them. A tiny store keeps hovering from
// re-rendering the whole scene.
import { Html } from '@react-three/drei'
import type { ThreeEvent } from '@react-three/fiber'
import { useSyncExternalStore } from 'react'
import * as THREE from 'three'
import type { Scene } from '../api'
import { fmt } from '../api'
import { ROWS, modulesPerRow } from './layout'

export interface HoverInfo { key: string; point: THREE.Vector3; id?: number }
let current: HoverInfo | null = null
const subs = new Set<() => void>()
const store = {
  get: () => current,
  set: (h: HoverInfo | null) => { current = h; subs.forEach((f) => f()) },
  sub: (f: () => void) => { subs.add(f); return () => { subs.delete(f) } },
}

/** Spread onto a mesh / group / instancedMesh: <mesh {...hov('transformer')} /> */
export function hov(key: string, fixedId?: number) {
  return {
    onPointerOver: (e: ThreeEvent<PointerEvent>) => {
      e.stopPropagation()
      store.set({ key, point: e.point.clone(), id: fixedId ?? e.instanceId })
      document.body.style.cursor = 'help'
    },
    onPointerOut: (e: ThreeEvent<PointerEvent>) => {
      e.stopPropagation()
      if (current?.key === key) store.set(null)
      document.body.style.cursor = ''
    },
  }
}

// panel instance id -> row (instances are laid out row by row, two modules per position)
const ROW_OF: number[] = (() => {
  const out: number[] = []
  modulesPerRow().forEach((n, ri) => { for (let i = 0; i < n; i++) out.push(ri) })
  return out
})()

type Line = string | null | false
function describe(h: HoverInfo, scene: Scene | null, inverterRow: (id: number) => number | undefined): { title: string; lines: Line[]; tag?: 'calc' | 'illus' | 'real' | 'approx' } {
  const w = scene?.weather, p = scene?.panels
  switch (h.key) {
    case 'panel': {
      const r = ROWS[ROW_OF[h.id ?? 0] ?? 0]
      return { title: `Solar panel · row ${r.id} (block ${r.block})`, tag: 'real', lines: [
        'Jinko JKM315PP-72 · 315 W · 72 cells', 'tilt 15° facing north · 2 portrait deep',
        `cell temperature ${fmt(p?.t_cell_c, 1)} °C · heat loss ${fmt(p?.heat_loss_pct, 1)}%`,
        `sunlight on panel ${fmt(w?.poa_wm2, 0)} W/m²`] }
    }
    case 'inverter': {
      const row = inverterRow(h.id ?? 0)
      return { title: `String inverter #${(h.id ?? 0) + 1} of 42`, tag: 'calc', lines: [
        'SMA STP 25000TL-30 · DC → AC · 25 kW', `row ${row ?? '—'} · 4 strings × 20 modules`,
        `equipment probe ${fmt(scene?.equipment.temp_c, 1)} °C`, 'count calculated · position illustrative'] }
    }
    case 'dc': return { title: `DC string cables · row ${(h.id ?? 0) + 1}`, tag: 'calc', lines: [
      'in a tray under the rear rail', 'strings of 20 modules · up to ~924 V open-circuit', 'blue dashes = DC power flowing'] }
    case 'trench': return { title: 'AC cable trench (underground)', tag: 'illus', lines: [
      'inverters → AC switchboard', `AC power now ${fmt(Math.max(0, scene?.power.measured_kw ?? 0), 0)} kW (amber dashes)`, 'route illustrative'] }
    case 'switchroom': return { title: 'Switch room · AC switchboard', tag: 'approx', lines: [
      `equipment probe ${fmt(scene?.equipment.temp_c, 1)} °C`, 'position approximate'] }
    case 'transformer': return { title: 'Step-up transformer', tag: 'illus', lines: ['inverter AC → grid voltage', 'rating and position not published'] }
    case 'rmu': return { title: 'Ring main unit', tag: 'illus', lines: ['grid-side switchgear', 'position illustrative'] }
    case 'logger': return { title: 'Data logger + comms', tag: 'illus', lines: ['sends the 5-minute readings to DKASC', 'position illustrative'] }
    case 'grid': return { title: 'Grid connection', tag: 'illus', lines: ['overhead line to the Yulara network', 'route illustrative'] }
    case 'gate': return { title: 'Gate', tag: 'illus', lines: ['access to the switch room'] }
    case 'fence': return { title: 'Security fence', tag: 'real', lines: ['≈ 269 × 116 m (from map data)'] }
    case 'mast': return { title: 'Weather station', tag: 'approx', lines: [
      `wind ${fmt(w?.wind_ms, 1)} m/s from ${fmt(w?.wind_from_deg, 0)}° · air ${fmt(w?.t_air_c, 1)} °C`,
      `ground sunlight (GHI) ${fmt(Math.max(0, w?.ghi_wm2 ?? 0), 0)} W/m²`,
      'vane + cups · level (GHI) and tilted (POA) pyranometers · temperature shield', 'position approximate'] }
    case 'light': return { title: 'Light pole', tag: 'illus', lines: ['switches on after sunset (sun elevation)', 'positions illustrative'] }
    case 'uluru': return { title: 'Uluru', tag: 'real', lines: ['≈ 12.6 km SSE · 348 m above the plain', 'real position · shape stylised'] }
    case 'kata': return { title: 'Kata Tjuta', tag: 'real', lines: ['≈ 26 km WSW · highest dome 546 m', 'real position · domes stylised'] }
    case 'hotel': return { title: 'Desert Gardens Hotel', tag: 'approx', lines: ['≈ 270 m west of the plant', 'buildings simplified'] }
    case 'road': return { title: 'Yulara Drive', tag: 'approx', lines: ['line approximate'] }
    case 'oak': return { title: 'Desert oak', tag: 'illus', lines: ['Allocasuarina decaisneana · 5–14 m', 'sways with the real wind'] }
    default: return { title: h.key, lines: [] }
  }
}

const TAG_TEXT = { calc: 'calculated', illus: 'illustrative', real: 'real', approx: 'approx.' }

export function HoverTag({ scene, inverterRow }: { scene: Scene | null; inverterRow: (id: number) => number | undefined }) {
  const h = useSyncExternalStore(store.sub, store.get)
  if (!h) return null
  const d = describe(h, scene, inverterRow)
  return (
    <Html position={h.point} center={false} zIndexRange={[30, 20]} style={{ pointerEvents: 'none', transform: 'translate(14px, -50%)' }}>
      <div className="tag hover-tag">
        <b>{d.title} {d.tag && <em className={`kind ${d.tag}`}>{TAG_TEXT[d.tag]}</em>}</b>
        {d.lines.filter(Boolean).map((l, i) => <span key={i}>{l}</span>)}
      </div>
    </Html>
  )
}
