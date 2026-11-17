// Electrical hardware of the plant. The real single-line diagram and equipment positions are NOT published,
// so this is a CALCULATED design that fits every known number, shown as illustrative:
//   module Voc 46.2 V x 20 in series = 924 V  (< 1,000 V inverter max input)  -> strings of 20 modules
//   3,360 modules / 20 = 168 strings ; 168 / 42 inverters = 4 strings per inverter
//   4 strings x 20 x 315 W = 25.2 kW DC per 25 kW inverter (SMA STP 25000TL-30, the inverter model is from DKASC)
// Chain: modules -> DC string cables (on the racks) -> string inverter (DC->AC, at the row) -> AC cables in
// trenches -> AC switchboard in the switch room -> step-up transformer + ring main unit -> grid line.
// Animated: DC flow (blue) along the rows and inverters warming, from measured power and the equipment probe.
import { Line } from '@react-three/drei'
import { useFrame } from '@react-three/fiber'
import { useLayoutEffect, useMemo, useRef } from 'react'
import * as THREE from 'three'
import type { Scene } from '../api'
import { EQUIPMENT, FENCE, ROWS, modulesPerRow } from './layout'
import { hov } from './hover'

export const STRING_LEN = 20
export const STRINGS_PER_INV = 4
const INV = { w: 0.66, h: 0.68, d: 0.26 } // SMA STP 25000TL-30 housing, metres (approx. datasheet size)

export interface Inverter { id: number; row: number; x: number; z: number }

/** 42 inverters: each row gets (its modules / 80) inverters, spread evenly along its north edge. */
export function placeInverters(): Inverter[] {
  const mods = modulesPerRow()
  const per = STRING_LEN * STRINGS_PER_INV
  const raw = mods.map((m) => m / per)
  const n = raw.map(Math.floor)
  let left = Math.round(mods.reduce((a, b) => a + b, 0) / per) - n.reduce((a, b) => a + b, 0)
  raw.map((v, i) => [v - Math.floor(v), i] as const).sort((a, b) => b[0] - a[0]).forEach(([, i]) => { if (left-- > 0) n[i]++ })
  const out: Inverter[] = []
  ROWS.forEach((r, ri) => {
    const k = n[ri], len = r.x1 - r.x0
    for (let j = 0; j < k; j++) out.push({ id: out.length + 1, row: r.id, x: r.x0 + (len * (j + 0.5)) / k, z: r.z - 0.75 })
  })
  return out
}

const TRUNK_X = EQUIPMENT.x - 1.5 // main AC trench, same line as the AC power-flow dashes

function Inverters({ scene, invs }: { scene: Scene | null; invs: Inverter[] }) {
  const body = useRef<THREE.InstancedMesh>(null!)
  const lid = useRef<THREE.InstancedMesh>(null!)
  const posts = useRef<THREE.InstancedMesh>(null!)
  const mat = useRef<THREE.MeshStandardMaterial>(null!)
  const heat = useRef(0)
  useLayoutEffect(() => {
    const o = new THREE.Object3D()
    invs.forEach((v, i) => {
      o.position.set(v.x, 0.75 + INV.h / 2, v.z); o.updateMatrix(); body.current.setMatrixAt(i, o.matrix)
      o.position.set(v.x, 0.75 + INV.h + 0.03, v.z); o.updateMatrix(); lid.current.setMatrixAt(i, o.matrix) // sun shade
      ;[-0.25, 0.25].forEach((dx, k) => { o.position.set(v.x + dx, 0.6, v.z + 0.16); o.updateMatrix(); posts.current.setMatrixAt(i * 2 + k, o.matrix) })
    })
    for (const r of [body, lid, posts]) r.current.instanceMatrix.needsUpdate = true
  }, [invs])
  useFrame((_, dt) => {
    // casing warms visibly above 55 °C on the equipment probe (the site's equipment temperature sensor)
    const t = scene?.equipment.temp_c ?? 30
    heat.current += (THREE.MathUtils.clamp((t - 55) / 25, 0, 1) - heat.current) * (1 - Math.exp(-dt * 2))
    mat.current.emissiveIntensity = heat.current * 0.6
  })
  return (
    <group>
      <instancedMesh ref={body} args={[undefined, undefined, invs.length]} castShadow {...hov('inverter')}>
        <boxGeometry args={[INV.w, INV.h, INV.d]} />
        <meshStandardMaterial ref={mat} color="#e4e7ea" roughness={0.45} metalness={0.2} emissive="#ff4a2a" emissiveIntensity={0} />
      </instancedMesh>
      <instancedMesh ref={lid} args={[undefined, undefined, invs.length]} castShadow>
        <boxGeometry args={[INV.w + 0.25, 0.04, INV.d + 0.35]} />
        <meshStandardMaterial color="#b9bec6" metalness={0.7} roughness={0.35} />
      </instancedMesh>
      <instancedMesh ref={posts} args={[undefined, undefined, invs.length * 2]} castShadow>
        <boxGeometry args={[0.06, 1.2, 0.06]} />
        <meshStandardMaterial color="#9aa2b0" metalness={0.8} roughness={0.35} />
      </instancedMesh>
    </group>
  )
}

/** DC string cables in a tray under each row's rear rail, plus the drop to each inverter; blue dashes = DC flow. */
function DcCabling({ scene, invs }: { scene: Scene | null; invs: Inverter[] }) {
  const trays = useMemo(() => ROWS.map((r) => [[r.x0 + 0.5, 1.05, r.z + 3.05], [r.x1 - 0.5, 1.05, r.z + 3.05]] as [number, number, number][]), [])
  const drops = useMemo(() => invs.map((v) => [[v.x, 1.05, v.z + 3.8], [v.x, 0.3, v.z + 2.2], [v.x, 0.3, v.z + 0.4], [v.x, 0.85, v.z + 0.14]] as [number, number, number][]), [invs])
  const flow = useRef<(THREE.Object3D | null)[]>([])
  const kw = useRef(0)
  useFrame((_, dt) => {
    kw.current += (Math.max(0, scene?.power.measured_kw ?? 0) - kw.current) * (1 - Math.exp(-dt * 2))
    const f = kw.current / 1058
    flow.current.forEach((l) => {
      if (!l) return
      const m = (l as unknown as { material: { dashOffset: number; opacity: number } }).material
      m.dashOffset -= dt * (0.4 + 14 * f)
      m.opacity = f < 0.01 ? 0 : 0.35 + 0.6 * Math.min(1, f * 1.5)
    })
  })
  return (
    <group>
      {trays.map((p, i) => <Line key={`t${i}`} points={p} color="#1b1d21" lineWidth={2.4} />)}
      {/* invisible hit boxes so the tray can be hovered */}
      {trays.map((p, i) => (
        <mesh key={`h${i}`} {...hov('dc', i)} position={[(p[0][0] + p[1][0]) / 2, p[0][1], p[0][2]]}>
          <boxGeometry args={[p[1][0] - p[0][0], 0.35, 0.45]} />
          <meshBasicMaterial transparent opacity={0} depthWrite={false} />
        </mesh>
      ))}
      {drops.map((p, i) => <Line key={`d${i}`} points={p} color="#1b1d21" lineWidth={1.6} />)}
      {trays.map((p, i) => (
        <Line key={`f${i}`} ref={(el) => { flow.current[i] = el as unknown as THREE.Object3D }} points={[[p[0][0], p[0][1] + 0.06, p[0][2]], [p[1][0], p[1][1] + 0.06, p[1][2]]]}
          color="#5ab0ff" lineWidth={2} dashed dashSize={1.2} gapSize={2.4} transparent opacity={0} depthWrite={false} />
      ))}
    </group>
  )
}

/** AC cables run underground: a trench strip along each row's north side and one main trench to the switch room. */
function AcTrenches() {
  const strips = useMemo(() => {
    const s: [number, number, number, number][] = [] // cx, cz, w, d
    ROWS.forEach((r) => {
      const x0 = Math.min(r.x0, TRUNK_X), x1 = Math.max(r.x1, TRUNK_X)
      s.push([(x0 + x1) / 2, r.z - 0.6, x1 - x0, 0.8])
    })
    const zEnd = ROWS[ROWS.length - 1].z - 0.6
    s.push([TRUNK_X, (EQUIPMENT.z + 2 + zEnd) / 2, 1.1, zEnd - EQUIPMENT.z - 2])
    return s
  }, [])
  return (
    <group>
      {strips.map(([x, z, w, d], i) => (
        <mesh key={i} rotation-x={-Math.PI / 2} position={[x, 0.045, z]} receiveShadow {...hov('trench')}>
          <planeGeometry args={[w, d]} />
          <meshStandardMaterial color="#5e4a3c" roughness={1} transparent opacity={0.75} polygonOffset polygonOffsetFactor={-1} />
        </mesh>
      ))}
    </group>
  )
}

/** Outside the switch room: step-up transformer, ring main unit, data logger + antenna, grid line, gate. */
function Yard() {
  const T = { x: EQUIPMENT.x + 15, z: EQUIPMENT.z - 0.5 }
  const RMU = { x: EQUIPMENT.x + 20.5, z: EQUIPMENT.z - 0.5 }
  const fins = useMemo(() => Array.from({ length: 9 }, (_, i) => -1 + i * 0.25), [])
  // grid line: overhead poles heading north out of the fence (route illustrative)
  const poles = useMemo(() => [0, 1, 2, 3].map((i) => ({ x: RMU.x + 2, z: FENCE.z0 - 4 - i * 55 })), [RMU.x])
  const wires = useMemo(() => [-0.9, 0, 0.9].map((dx) => {
    const pts: [number, number, number][] = [[RMU.x + 0.4 + dx * 0.3, 2.2, RMU.z]]
    poles.forEach((p, i) => {
      if (i > 0) { const prev = poles[i - 1]; pts.push([p.x + dx, 8.6 - 0.9, (prev.z + p.z) / 2]) } // sag
      pts.push([p.x + dx, 9.6, p.z])
    })
    return pts
  }), [poles, RMU.x, RMU.z])
  return (
    <group>
      {/* step-up transformer on a concrete pad, with cooling fins and bushings */}
      <mesh position={[T.x, 0.1, T.z]} receiveShadow><boxGeometry args={[4, 0.2, 3]} /><meshStandardMaterial color="#b9b6ae" roughness={0.9} /></mesh>
      <mesh position={[T.x, 1.15, T.z]} castShadow {...hov('transformer')}><boxGeometry args={[2.2, 1.9, 1.4]} /><meshStandardMaterial color="#7d8a7f" metalness={0.4} roughness={0.5} /></mesh>
      {fins.map((dx, i) => (
        <group key={i}>
          <mesh position={[T.x + dx, 1.05, T.z + 0.85]} castShadow><boxGeometry args={[0.05, 1.5, 0.3]} /><meshStandardMaterial color="#6f7b71" metalness={0.4} roughness={0.5} /></mesh>
          <mesh position={[T.x + dx, 1.05, T.z - 0.85]} castShadow><boxGeometry args={[0.05, 1.5, 0.3]} /><meshStandardMaterial color="#6f7b71" metalness={0.4} roughness={0.5} /></mesh>
        </group>
      ))}
      {[-0.6, 0, 0.6].map((dx, i) => (
        <mesh key={i} position={[T.x + dx, 2.35, T.z]}><cylinderGeometry args={[0.07, 0.1, 0.5, 8]} /><meshStandardMaterial color="#8a5a3a" roughness={0.4} /></mesh>
      ))}
      {/* ring main unit (grid-side switchgear) */}
      <mesh position={[RMU.x, 1.0, RMU.z]} castShadow {...hov('rmu')}><boxGeometry args={[1.6, 2, 1]} /><meshStandardMaterial color="#c9ccd0" metalness={0.5} roughness={0.4} /></mesh>
      {/* data logger / comms cabinet with antenna, on the switch room's west wall */}
      <mesh position={[EQUIPMENT.x - 5.2, 1.4, EQUIPMENT.z + 1]} castShadow {...hov('logger')}><boxGeometry args={[0.6, 0.8, 0.3]} /><meshStandardMaterial color="#dfe2e6" roughness={0.5} /></mesh>
      <mesh position={[EQUIPMENT.x - 5.2, 4.2, EQUIPMENT.z + 1]}><cylinderGeometry args={[0.02, 0.02, 4.8, 6]} /><meshStandardMaterial color="#9ca3ad" metalness={0.8} /></mesh>
      {/* grid line poles + three conductors */}
      {poles.map((p, i) => (
        <group key={i} position={[p.x, 0, p.z]} {...hov('grid')}>
          <mesh position={[0, 5, 0]} castShadow><cylinderGeometry args={[0.14, 0.18, 10, 8]} /><meshStandardMaterial color="#6b5a48" roughness={0.9} /></mesh>
          <mesh position={[0, 9.6, 0]}><boxGeometry args={[2.4, 0.12, 0.12]} /><meshStandardMaterial color="#6b5a48" roughness={0.9} /></mesh>
        </group>
      ))}
      {wires.map((w, i) => <Line key={i} points={w} color="#2a2c30" lineWidth={1.2} />)}
      {/* gate in the north fence next to the switch room */}
      {[-1, 1].map((s) => (
        <mesh key={s} position={[EQUIPMENT.x + 30 + s * 1.6, 1, FENCE.z0]} rotation-y={s * 0.35} {...hov('gate')}>
          <boxGeometry args={[3, 1.9, 0.05]} /><meshStandardMaterial color="#a8afb8" metalness={0.7} roughness={0.4} transparent opacity={0.6} />
        </mesh>
      ))}
    </group>
  )
}

export default function Hardware({ scene }: { scene: Scene | null }) {
  const invs = useMemo(placeInverters, [])
  return (
    <group>
      <Inverters scene={scene} invs={invs} />
      <DcCabling scene={scene} invs={invs} />
      <AcTrenches />
      <Yard />
    </group>
  )
}
