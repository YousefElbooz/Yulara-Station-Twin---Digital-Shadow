// The 3D station. Every moving or coloured thing here is driven by a number from /api/scene or /api/now:
//   sun position + light   <- scene.sun (pvlib), scene.weather.ghi_wm2
//   panel colour (heat)    <- scene.panels.t_cell_c
//   panel colour (dust)    <- scene.panels.dust_index (low confidence)
//   panel glow             <- scene.weather.poa_wm2
//   wind strokes / dust    <- scene.weather.wind_ms, wind_from_deg   (Weather.tsx)
//   rain, grey haze        <- scene.weather.rain_mm_h, cloud_cover (ERA5)
//   trees swaying          <- scene.weather.wind_ms (World.tsx)
//   power-flow dashes      <- scene.power.measured_kw
//   alarm markers          <- open alarms
// Positions of the equipment building and weather mast are approximate (no ground photos).
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { Environment, Html, Line, OrbitControls, Sky, Stars } from '@react-three/drei'
import { Suspense, useLayoutEffect, useMemo, useRef } from 'react'
import type { OrbitControls as OrbitImpl } from 'three-stdlib'
import { Bloom, EffectComposer, N8AO, SMAA, ToneMapping, Vignette } from '@react-three/postprocessing'
import { ToneMappingMode } from 'postprocessing'
import { useEffect } from 'react'
import * as THREE from 'three'
import type { Alarm, Scene } from '../api'
import { ALARM_LABEL } from '../api'
import { CENTER, EQUIPMENT, FENCE, MAST, MODULE_L, MODULE_W, ROWS, TILT_DEG, modulesPerRow } from './layout'
import World, { ULURU } from './World'
import NightLights from './NightLights'
import Weather from './Weather'
import Hardware, { placeInverters } from './Hardware'
import { HoverTag, hov } from './hover'

const DEG = Math.PI / 180

/** Unit vector toward the sun. Azimuth from north, clockwise; north is -z, east is +x. */
function sunVector(elDeg: number, azDeg: number) {
  const el = elDeg * DEG, az = azDeg * DEG
  return new THREE.Vector3(Math.sin(az) * Math.cos(el), Math.sin(el), -Math.cos(az) * Math.cos(el))
}

const C_PANEL = new THREE.Color('#ffffff') // multiplies the cell texture
const C_COOL_GLOW = new THREE.Color('#2b4cff')
const C_HOT = new THREE.Color('#ff7a1a')
const C_DUST = new THREE.Color('#b48a58')
const C_FLOW = new THREE.Color('#ffb020')

export type View = 'overview' | 'ground' | 'landscape' | 'top'
export interface SceneTargets { scene: Scene | null; alarms: Alarm[]; view: View; fx: boolean }

/** A 72-cell polycrystalline module (6 x 12 cells), drawn once on a canvas: blue cells, silver busbars, frame. */
function makeCellTexture() {
  const W = 96, H = 192, c = document.createElement('canvas')
  c.width = W; c.height = H
  const g = c.getContext('2d')!
  g.fillStyle = '#c9ced6'; g.fillRect(0, 0, W, H) // aluminium frame
  const pad = 3, cw = (W - pad * 2) / 6, ch = (H - pad * 2) / 12
  for (let i = 0; i < 6; i++) for (let j = 0; j < 12; j++) {
    const x = pad + i * cw, y = pad + j * ch
    const l = 18 + Math.random() * 10 // polycrystalline: each cell a slightly different blue
    g.fillStyle = 'hsl(' + (218 + Math.random() * 8) + ', 62%, ' + l + '%)'
    g.fillRect(x + 0.6, y + 0.6, cw - 1.2, ch - 1.2)
    g.fillStyle = 'rgba(255,255,255,0.05)'
    for (let k = 0; k < 4; k++) g.fillRect(x + Math.random() * cw, y + Math.random() * ch, 3 + Math.random() * 4, 2 + Math.random() * 3)
    g.fillStyle = 'rgba(210,215,225,0.55)' // two busbars per cell
    g.fillRect(x + cw * 0.3, y, 0.7, ch); g.fillRect(x + cw * 0.7, y, 0.7, ch)
  }
  const t = new THREE.CanvasTexture(c)
  t.colorSpace = THREE.SRGBColorSpace
  t.anisotropy = 8
  return t
}

// ------------------------------------------------------------------ panels
function Panels({ scene }: { scene: Scene | null }) {
  const mesh = useRef<THREE.InstancedMesh>(null!)
  const mat = useRef<THREE.MeshPhysicalMaterial>(null!)
  const counts = useMemo(modulesPerRow, [])
  const total = counts.reduce((a, b) => a + b, 0)
  const jitter = useMemo(() => Float32Array.from({ length: total }, () => Math.random() * 0.06 - 0.03), [total])
  const cur = useRef({ heat: 0, dust: 0, glow: 0, frame: 0 })
  const cells = useMemo(makeCellTexture, [])

  useLayoutEffect(() => {
    const o = new THREE.Object3D()
    const t = TILT_DEG * DEG
    let k = 0
    ROWS.forEach((r, ri) => {
      const perLine = counts[ri] / 2
      const len = r.x1 - r.x0
      const step = len / perLine
      for (let j = 0; j < perLine; j++) {
        for (const v of [-1, 1]) { // two portrait modules up the slope
          const along = v * (MODULE_L / 2 + 0.01)
          o.position.set(r.x0 + step * (j + 0.5), 1.1 + along * Math.sin(t), r.z + 1.9 + along * Math.cos(t))
          o.rotation.set(-t, 0, 0) // normal tilted toward north (-z)
          o.updateMatrix()
          mesh.current.setMatrixAt(k, o.matrix)
          mesh.current.setColorAt(k, C_PANEL)
          k++
        }
      }
    })
    mesh.current.instanceMatrix.needsUpdate = true
    mesh.current.instanceColor!.needsUpdate = true
    mesh.current.computeBoundingSphere()
    ;(mesh.current.material as THREE.Material).needsUpdate = true
  }, [counts])

  useFrame((_, dt) => {
    const c = cur.current
    const tc = scene?.panels.t_cell_c ?? 25
    const heatT = THREE.MathUtils.clamp((tc - 25) / 45, 0, 1) // 25 °C -> 0, 70 °C -> 1
    const dustT = scene?.panels.dust_index != null ? THREE.MathUtils.clamp((1 - scene.panels.dust_index) / 0.15, 0, 1) : 0
    const glowT = THREE.MathUtils.clamp((scene?.weather.poa_wm2 ?? 0) / 1000, 0, 1.2)
    const a = 1 - Math.exp(-dt * 2) // ~600 ms ease toward the new value
    c.heat += (heatT - c.heat) * a
    c.dust += (dustT - c.dust) * a
    c.glow += (glowT - c.glow) * a
    // heat shows as a warm glow (emissive), dust as a brown film on the base colour, so the two never mix
    mat.current.emissive.copy(C_COOL_GLOW).lerp(C_HOT, c.heat)
    mat.current.emissiveIntensity = 0.005 + c.glow * 0.02 + c.heat * 0.22
    if (c.frame++ % 8) return // recolour 3,360 instances only every 8th frame
    const col = new THREE.Color()
    for (let i = 0; i < total; i++) {
      col.copy(C_PANEL).lerp(C_DUST, c.dust * 0.7)
      col.offsetHSL(0, 0, jitter[i] * 2)
      mesh.current.setColorAt(i, col)
    }
    mesh.current.instanceColor!.needsUpdate = true
  })

  return (
    <instancedMesh ref={mesh} args={[undefined, undefined, total]} castShadow receiveShadow {...hov('panel')}>
      <boxGeometry args={[MODULE_W * 0.97, 0.04, MODULE_L * 0.98]} />
      {/* glass over cells: a clear coat that reflects the real sky (environment map below) */}
      <meshPhysicalMaterial ref={mat} map={cells} metalness={0.2} roughness={0.5} clearcoat={0.55} clearcoatRoughness={0.08}
        envMapIntensity={0.35} emissive="#3a5cff" emissiveIntensity={0.02} />
    </instancedMesh>
  )
}

/** Steel frames under each row: two rails plus posts every ~4 m. */
function Frames() {
  const posts = useMemo(() => {
    const p: [number, number, number, number][] = []
    for (const r of ROWS) for (let x = r.x0 + 1; x < r.x1; x += 4) { p.push([x, r.z + 0.25, 0.85, 0]); p.push([x, r.z + 3.55, 1.85, 1]) }
    return p
  }, [])
  const ref = useRef<THREE.InstancedMesh>(null!)
  const rails = useRef<THREE.InstancedMesh>(null!)
  useLayoutEffect(() => {
    const o = new THREE.Object3D()
    posts.forEach(([x, z, h], i) => { o.position.set(x, h / 2, z); o.scale.set(1, h, 1); o.updateMatrix(); ref.current.setMatrixAt(i, o.matrix) })
    ref.current.instanceMatrix.needsUpdate = true
    ROWS.forEach((r, i) => {
      const len = r.x1 - r.x0
      const lines: [number, number][] = [[r.z + 0.6, 0.78], [r.z + 3.2, 1.48]]
      lines.forEach(([z, y], k) => {
        o.position.set((r.x0 + r.x1) / 2, y, z); o.scale.set(len, 1, 1); o.updateMatrix(); rails.current.setMatrixAt(i * 2 + k, o.matrix)
      })
    })
    rails.current.instanceMatrix.needsUpdate = true
  }, [posts])
  return (
    <group>
      <instancedMesh ref={ref} args={[undefined, undefined, posts.length]} castShadow>
        <boxGeometry args={[0.1, 1, 0.1]} />
        <meshStandardMaterial color="#9aa2b0" metalness={0.8} roughness={0.35} />
      </instancedMesh>
      <instancedMesh ref={rails} args={[undefined, undefined, ROWS.length * 2]} castShadow>
        <boxGeometry args={[1, 0.08, 0.12]} />
        <meshStandardMaterial color="#aab1bd" metalness={0.85} roughness={0.3} />
      </instancedMesh>
    </group>
  )
}

// ------------------------------------------------------------------ ground, fence, buildings
/** Chain-link security fence: posts every 3 m and a see-through mesh panel. */
function Fence() {
  const sides = useMemo<[number, number, number, number][]>(() => [
    [FENCE.x0, FENCE.z0, FENCE.x1, FENCE.z0], [FENCE.x1, FENCE.z0, FENCE.x1, FENCE.z1],
    [FENCE.x1, FENCE.z1, FENCE.x0, FENCE.z1], [FENCE.x0, FENCE.z1, FENCE.x0, FENCE.z0],
  ], [])
  const postPos = useMemo(() => {
    const p: [number, number][] = []
    sides.forEach(([x0, z0, x1, z1]) => {
      const len = Math.hypot(x1 - x0, z1 - z0), n = Math.round(len / 3)
      for (let i = 0; i < n; i++) p.push([x0 + ((x1 - x0) * i) / n, z0 + ((z1 - z0) * i) / n])
    })
    return p
  }, [sides])
  const ref = useRef<THREE.InstancedMesh>(null!)
  useLayoutEffect(() => {
    const o = new THREE.Object3D()
    postPos.forEach(([x, z], i) => { o.position.set(x, 1, z); o.updateMatrix(); ref.current.setMatrixAt(i, o.matrix) })
    ref.current.instanceMatrix.needsUpdate = true
  }, [postPos])
  return (
    <group>
      <instancedMesh ref={ref} args={[undefined, undefined, postPos.length]} castShadow>
        <cylinderGeometry args={[0.04, 0.04, 2, 6]} />
        <meshStandardMaterial color="#9ca3ad" metalness={0.8} roughness={0.4} />
      </instancedMesh>
      {sides.map(([x0, z0, x1, z1], i) => (
        <mesh key={i} position={[(x0 + x1) / 2, 1, (z0 + z1) / 2]} rotation-y={-Math.atan2(z1 - z0, x1 - x0)} {...hov('fence')}>
          <planeGeometry args={[Math.hypot(x1 - x0, z1 - z0), 2]} />
          <meshStandardMaterial color="#b8bec8" transparent opacity={0.16} side={THREE.DoubleSide} depthWrite={false} metalness={0.6} />
        </mesh>
      ))}
    </group>
  )
}

function Ground() {
  return (
    <group>
      <Fence />
      {/* north arrow */}
      <group position={[FENCE.x1 + 18, 0.05, FENCE.z0 + 6]}>
        <mesh rotation-x={-Math.PI / 2}>
          <coneGeometry args={[2.2, 7, 3]} />
          <meshBasicMaterial color="#30d5c8" />
        </mesh>
        <Html position={[0, 0, -7]} center className="tag tag-n">N</Html>
      </group>
    </group>
  )
}

function Equipment({ hot }: { hot: boolean }) {
  const mat = useRef<THREE.MeshPhysicalMaterial>(null!)
  useFrame(({ clock }) => {
    mat.current.emissiveIntensity = hot ? 0.35 + 0.25 * Math.sin(clock.elapsedTime * 4) : 0
  })
  return (
    <group position={[EQUIPMENT.x, 0, EQUIPMENT.z]} {...hov('switchroom')}>
      <mesh position={[0, 1.6, 0]} castShadow receiveShadow>
        <boxGeometry args={[9, 3.2, 4]} />
        <meshStandardMaterial ref={mat} color="#d8dbe2" roughness={0.7} emissive="#ff5c7a" emissiveIntensity={0} />
      </mesh>
      <mesh position={[7, 1.1, 0]} castShadow>
        <boxGeometry args={[3, 2.2, 2.4]} />
        <meshStandardMaterial color="#6f7a8c" roughness={0.6} metalness={0.4} />
      </mesh>
    </group>
  )
}

function WeatherMast({ scene }: { scene: Scene | null }) {
  const vane = useRef<THREE.Group>(null!)
  const cups = useRef<THREE.Group>(null!)
  useFrame((_, dt) => {
    const from = scene?.weather.wind_from_deg
    if (from != null) {
      // the vane points INTO the wind (toward where it comes from)
      const target = -from * DEG
      vane.current.rotation.y += (target - vane.current.rotation.y) * (1 - Math.exp(-dt * 2))
    }
    cups.current.rotation.y += (scene?.weather.wind_ms ?? 0) * dt * 1.6
  })
  return (
    <group position={[MAST.x, 0, MAST.z]} {...hov('mast')}>
      <mesh position={[0, 5, 0]}>
        <cylinderGeometry args={[0.08, 0.1, 10, 8]} />
        <meshStandardMaterial color="#c9ced8" metalness={0.6} roughness={0.4} />
      </mesh>
      <group ref={vane} position={[0, 10, 0]}>
        <mesh position={[0, 0, -0.9]} rotation-x={-Math.PI / 2}>
          <coneGeometry args={[0.18, 0.7, 8]} />
          <meshStandardMaterial color="#30d5c8" />
        </mesh>
        <mesh position={[0, 0, 0.6]}>
          <boxGeometry args={[0.04, 0.5, 0.9]} />
          <meshStandardMaterial color="#30d5c8" />
        </mesh>
      </group>
      <group ref={cups} position={[0, 10.8, 0]}>
        {[0, 1, 2].map((i) => (
          <mesh key={i} position={[Math.cos((i * 2 * Math.PI) / 3) * 0.55, 0, Math.sin((i * 2 * Math.PI) / 3) * 0.55]}>
            <sphereGeometry args={[0.16, 10, 8]} />
            <meshStandardMaterial color="#e8ebf1" />
          </mesh>
        ))}
      </group>
      {/* GHI pyranometer: level, on an arm to the east */}
      <mesh position={[0.8, 8.2, 0]}><boxGeometry args={[1.6, 0.05, 0.05]} /><meshStandardMaterial color="#c9ced8" metalness={0.6} /></mesh>
      <mesh position={[1.6, 8.28, 0]}><cylinderGeometry args={[0.12, 0.12, 0.08, 16]} /><meshStandardMaterial color="#f2f3f5" /></mesh>
      <mesh position={[1.6, 8.32, 0]}><sphereGeometry args={[0.06, 16, 8, 0, Math.PI * 2, 0, Math.PI / 2]} /><meshPhysicalMaterial color="#ffffff" transmission={0.9} roughness={0.05} thickness={0.02} /></mesh>
      {/* pyranometer on a plate tilted 15 deg to the north, like the panels (Pyranometer_1 looks like plane-of-array, step 1) */}
      <mesh position={[-0.8, 8.2, 0]}><boxGeometry args={[1.6, 0.05, 0.05]} /><meshStandardMaterial color="#c9ced8" metalness={0.6} /></mesh>
      <group position={[-1.6, 8.3, 0]} rotation-x={-15 * DEG}>
        <mesh><boxGeometry args={[0.4, 0.03, 0.4]} /><meshStandardMaterial color="#9aa2b0" metalness={0.7} /></mesh>
        <mesh position={[0, 0.05, 0]}><cylinderGeometry args={[0.12, 0.12, 0.08, 16]} /><meshStandardMaterial color="#f2f3f5" /></mesh>
        <mesh position={[0, 0.09, 0]}><sphereGeometry args={[0.06, 16, 8, 0, Math.PI * 2, 0, Math.PI / 2]} /><meshPhysicalMaterial color="#ffffff" transmission={0.9} roughness={0.05} thickness={0.02} /></mesh>
      </group>
      {/* air-temperature sensor in a radiation shield (stacked white plates) */}
      {[0, 1, 2, 3, 4, 5].map((i) => (
        <mesh key={i} position={[0.3, 2.2 + i * 0.07, 0]}><cylinderGeometry args={[0.13 - i * 0.008, 0.15 - i * 0.008, 0.025, 16]} /><meshStandardMaterial color="#f4f5f7" /></mesh>
      ))}
    </group>
  )
}

// ------------------------------------------------------------------ power flow (dashes speed ∝ kW)
function PowerFlow({ scene }: { scene: Scene | null }) {
  const paths = useMemo(() => {
    const trunkX = EQUIPMENT.x - 1.5
    return ROWS.map((r) => {
      const xc = (r.x0 + r.x1) / 2
      const zc = r.z - 0.6
      return [[xc, 0.3, zc], [trunkX, 0.3, zc], [trunkX, 0.3, EQUIPMENT.z + 2.2]] as [number, number, number][]
    })
  }, [])
  const refs = useRef<(THREE.Object3D | null)[]>([])
  const cur = useRef({ kw: 0 })
  useFrame((_, dt) => {
    const kw = Math.max(0, scene?.power.measured_kw ?? 0)
    cur.current.kw += (kw - cur.current.kw) * (1 - Math.exp(-dt * 2))
    const f = cur.current.kw / 1050 // 0..1 of the AC rating (calculated)
    refs.current.forEach((l) => {
      if (!l) return
      const m = (l as unknown as { material: { dashOffset: number; opacity: number } }).material
      m.dashOffset -= dt * (0.5 + 22 * f)
      m.opacity = f < 0.01 ? 0.12 : 0.35 + 0.65 * Math.min(1, f * 1.4)
    })
  })
  return (
    <group>
      {paths.map((p, i) => (
        <Line key={i} ref={(el) => { refs.current[i] = el as unknown as THREE.Object3D }} points={p} color={C_FLOW}
          lineWidth={2.2} dashed dashSize={3} gapSize={4} transparent opacity={0.4} depthWrite={false} />
      ))}
    </group>
  )
}

// ------------------------------------------------------------------ alarm markers
const ALARM_POS: Record<string, [number, number, number]> = {
  OUTAGE: [CENTER.x + 20, 14, CENTER.z + 12],
  OFFLINE: [CENTER.x + 20, 14, CENTER.z + 12],
  FAULT: [CENTER.x - 40, 14, CENTER.z + 12],
  SOILING: [CENTER.x, 14, CENTER.z + 20],
  EQUIPMENT_HOT: [EQUIPMENT.x + 14, 16, EQUIPMENT.z],
  WEATHER_SENSORS_OFF: [MAST.x, 17, MAST.z],
}
const SEV_COLOR: Record<string, string> = { critical: '#ff5c7a', warning: '#ffb020', info: '#5ab0ff' }

function AlarmMarker({ alarm, i }: { alarm: Alarm; i: number }) {
  const ring = useRef<THREE.Mesh>(null!)
  const p = ALARM_POS[alarm.type] ?? [CENTER.x, 14, CENTER.z]
  const col = SEV_COLOR[alarm.severity] ?? '#ffb020'
  useFrame(({ clock }) => {
    const t = (clock.elapsedTime * 0.8 + i * 0.3) % 1
    ring.current.scale.setScalar(2 + t * 10)
    ;(ring.current.material as THREE.MeshBasicMaterial).opacity = 0.7 * (1 - t)
  })
  return (
    <group>
      <mesh ref={ring} rotation-x={-Math.PI / 2} position={[p[0], 0.15, p[2]]}>
        <ringGeometry args={[0.85, 1, 48]} />
        <meshBasicMaterial color={col} transparent depthWrite={false} />
      </mesh>
      <Line points={[[p[0], 0.2, p[2]], p]} color={col} lineWidth={1.5} transparent opacity={0.8} />
      <Html position={p} center distanceFactor={150} className={`alarm-tag sev-${alarm.severity}`}>
        <i>!</i>
        <b>{ALARM_LABEL[alarm.type] ?? alarm.type}</b>
      </Html>
    </group>
  )
}

// ------------------------------------------------------------------ sun, sky, light, haze
const C_SUN_LOW = new THREE.Color('#ff8a3d')
const C_SUN_HIGH = new THREE.Color('#fff3df')
const C_FOG_NIGHT = new THREE.Color('#05070d')
const C_FOG_DUSK = new THREE.Color('#b8704c')
const C_FOG_DAY = new THREE.Color('#d8b496')
const C_FOG_DUST = new THREE.Color('#c48a5c')
const C_FOG_RAIN = new THREE.Color('#8e9399')

function glowTexture() {
  const c = document.createElement('canvas'); c.width = c.height = 256
  const g = c.getContext('2d')!
  const grad = g.createRadialGradient(128, 128, 0, 128, 128, 128)
  grad.addColorStop(0, 'rgba(255,255,255,1)')
  grad.addColorStop(0.08, 'rgba(255,248,225,0.95)')
  grad.addColorStop(0.2, 'rgba(255,220,150,0.35)')
  grad.addColorStop(0.5, 'rgba(255,190,110,0.08)')
  grad.addColorStop(1, 'rgba(255,170,90,0)')
  g.fillStyle = grad; g.fillRect(0, 0, 256, 256)
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace
  return t
}

const SUN_DIST = 30000
function SunAndSky({ scene }: { scene: Scene | null }) {
  const light = useRef<THREE.DirectionalLight>(null!)
  const hemi = useRef<THREE.HemisphereLight>(null!)
  const halo = useRef<THREE.Sprite>(null!)
  const fog = useRef<THREE.FogExp2>(null!)
  const glow = useMemo(glowTexture, [])
  const cur = useRef({ dir: new THREE.Vector3(0, -1, 0), ghi: 0, wind: 0, rain: 0, cloud: 0 })
  const el = scene?.sun.elevation_deg ?? -30
  const az = scene?.sun.azimuth_deg ?? 0
  const target = useMemo(() => sunVector(el, az), [el, az])
  const night = el < -6
  // reflections in the panel glass: re-render the sky into an environment map every ~3 degrees of sun movement
  const envKey = `${Math.round(el / 3)}_${Math.round(az / 6)}`
  const skyProps = {
    sunPosition: [target.x, target.y, target.z] as [number, number, number],
    turbidity: (el < 10 ? 8 : 4.5) + (scene?.weather.cloud_cover ?? 0) * 6,
    rayleigh: el < 10 ? 2.6 : 1.1,
    mieCoefficient: 0.006,
    mieDirectionalG: 0.86,
  }

  useFrame(({ scene: s3 }, dt) => {
    const c = cur.current
    const a = 1 - Math.exp(-dt * 1.5)
    c.dir.lerp(target, a).normalize()
    c.ghi += ((Math.max(0, scene?.weather.ghi_wm2 ?? 0)) - c.ghi) * a
    c.wind += ((scene?.weather.wind_ms ?? 0) - c.wind) * a
    const elev = Math.asin(c.dir.y) / DEG
    const warm = THREE.MathUtils.clamp(elev / 25, 0, 1)
    // directional light: position from pvlib's sun, strength from measured GHI, colour warmer near the horizon
    light.current.position.set(CENTER.x + c.dir.x * 400, c.dir.y * 400, CENTER.z + c.dir.z * 400)
    light.current.target.position.set(CENTER.x, 0, CENTER.z)
    light.current.target.updateMatrixWorld()
    light.current.intensity = c.dir.y > 0 ? 0.3 + (c.ghi / 1000) * 3.4 : 0
    light.current.color.copy(C_SUN_LOW).lerp(C_SUN_HIGH, warm)
    hemi.current.intensity = c.dir.y > 0 ? 0.25 + (c.ghi / 1000) * 0.5 : 0.12
    s3.environmentIntensity = THREE.MathUtils.clamp(0.08 + c.dir.y * 1.4, 0.05, 1)
    // the sun you can see: a glow sprite far away in the sun's direction (angular size exaggerated)
    halo.current.position.set(CENTER.x + c.dir.x * SUN_DIST, c.dir.y * SUN_DIST, CENTER.z + c.dir.z * SUN_DIST)
    halo.current.visible = elev > -2
    const hs = SUN_DIST * (0.09 + (1 - warm) * 0.07)
    halo.current.scale.set(hs, hs, 1)
    ;(halo.current.material as THREE.SpriteMaterial).color.copy(C_SUN_LOW).lerp(C_SUN_HIGH, warm)
    // haze: night / dusk / day colour, thicker and dustier when the wind is strong (lifted dust)
    const dustT = THREE.MathUtils.clamp((c.wind - 5) / 8, 0, 1)
    const base = elev < -6 ? C_FOG_NIGHT : elev < 6 ? C_FOG_DUSK.clone().lerp(C_FOG_NIGHT, THREE.MathUtils.clamp((-elev + 6) / 12, 0, 1)) : C_FOG_DUSK.clone().lerp(C_FOG_DAY, THREE.MathUtils.clamp((elev - 6) / 20, 0, 1))
    const rainT = THREE.MathUtils.clamp((scene?.weather.rain_mm_h ?? 0) / 2, 0, 1)
    const cloudT = THREE.MathUtils.clamp(scene?.weather.cloud_cover ?? 0, 0, 1)
    c.rain += (rainT - c.rain) * a
    c.cloud += (cloudT - c.cloud) * a
    fog.current.color.copy(base).lerp(C_FOG_DUST, dustT * 0.6).lerp(C_FOG_RAIN.clone().multiplyScalar(elev < 0 ? 0.15 : 1), Math.max(c.rain, c.cloud * 0.5))
    fog.current.density = 0.000036 + dustT * 0.00012 + c.rain * 0.00025 + c.cloud * 0.00002
  })
  return (
    <>
      <Sky distance={60000} {...skyProps} />
      <Environment key={envKey} resolution={128} frames={1}>
        <Sky distance={1000} {...skyProps} />
      </Environment>
      <Stars radius={20000} depth={4000} count={night ? 5000 : 0} factor={320} fade speed={0.2} />
      <hemisphereLight ref={hemi} args={['#c9dcff', '#7a3a1e', 0.3]} />
      <directionalLight ref={light} castShadow color="#fff3dc"
        shadow-mapSize={[4096, 4096]} shadow-bias={-0.0003} shadow-normalBias={0.02}
        shadow-camera-left={-180} shadow-camera-right={180} shadow-camera-top={130} shadow-camera-bottom={-130}
        shadow-camera-near={10} shadow-camera-far={900} />
      <sprite ref={halo} renderOrder={-1}>
        <spriteMaterial map={glow} transparent depthWrite={false} fog={false} toneMapped={false} blending={THREE.AdditiveBlending} />
      </sprite>
      <fogExp2 ref={fog} attach="fog" args={['#d8b496', 0.000036]} />
    </>
  )
}

// ------------------------------------------------------------------ camera views
function towardUluru(from: [number, number, number], dist: number, y: number): [number, number, number] {
  const dx = ULURU.x - from[0], dz = ULURU.z - from[2], d = Math.hypot(dx, dz)
  return [from[0] + (dx / d) * dist, y, from[2] + (dz / d) * dist]
}
const GROUND_POS: [number, number, number] = [CENTER.x + 70, 3.6, FENCE.z0 - 22]
const LAND_POS: [number, number, number] = [CENTER.x - 420, 150, CENTER.z - 520]
const VIEWS: Record<View, { pos: [number, number, number]; target: [number, number, number] }> = {
  overview: { pos: [CENTER.x + 150, 115, CENTER.z + 190], target: [CENTER.x, 0, CENTER.z] },
  ground: { pos: GROUND_POS, target: towardUluru(GROUND_POS, 120, 1.2) },
  landscape: { pos: LAND_POS, target: towardUluru(LAND_POS, 1400, 0) },
  top: { pos: [CENTER.x, 430, CENTER.z + 1], target: [CENTER.x, 0, CENTER.z] },
}
function CameraRig({ view }: { view: View }) {
  const controls = useThree((s) => s.controls) as unknown as OrbitImpl | null
  const camera = useThree((s) => s.camera)
  const moving = useRef(true)
  useLayoutEffect(() => { moving.current = true }, [view])
  useFrame((_, dt) => {
    if (!moving.current || !controls) return
    const v = VIEWS[view]
    const a = 1 - Math.exp(-dt * 2.2)
    camera.position.lerp(new THREE.Vector3(...v.pos), a)
    controls.target.lerp(new THREE.Vector3(...v.target), a)
    controls.update()
    if (camera.position.distanceTo(new THREE.Vector3(...v.pos)) < 0.5) moving.current = false
  })
  // the user grabbing the camera stops the fly-to
  useLayoutEffect(() => {
    if (!controls) return
    const stop = () => { moving.current = false }
    controls.addEventListener('start', stop)
    return () => controls.removeEventListener('start', stop)
  }, [controls])
  return null
}

// ------------------------------------------------------------------ post-processing (looks only; no data in it)
//   N8AO: ambient occlusion -> contact shadows under panels, posts, trees and in the rows
//   Bloom: the sun's glare and the hot-panel glow; ToneMapping: filmic, as the renderer had; SMAA: anti-aliasing
function Effects() {
  return (
    <EffectComposer multisampling={0}>
      <N8AO halfRes quality="medium" aoRadius={2.5} distanceFalloff={1.2} intensity={2.4} color="#2b1408" />
      <Bloom mipmapBlur luminanceThreshold={0.9} luminanceSmoothing={0.25} intensity={0.6} />
      <ToneMapping mode={ToneMappingMode.ACES_FILMIC} />
      <Vignette offset={0.32} darkness={0.42} />
      <SMAA />
    </EffectComposer>
  )
}
/** With the composer on, tone mapping happens in the ToneMapping pass; without it, in the renderer. */
function RendererToneMapping({ fx }: { fx: boolean }) {
  const gl = useThree((s) => s.gl)
  useEffect(() => {
    gl.toneMapping = fx ? THREE.NoToneMapping : THREE.ACESFilmicToneMapping
    gl.toneMappingExposure = 0.85
  }, [gl, fx])
  return null
}

const INVS = placeInverters()
const inverterRow = (id: number) => INVS[id]?.row

export default function Station({ scene, alarms, view, fx }: SceneTargets) {
  const open = alarms.filter((a) => a.is_open)
  const hot = open.some((a) => a.type === 'EQUIPMENT_HOT')
  const night = (scene?.sun.elevation_deg ?? -30) < -6
  return (
    <Canvas shadows="soft" dpr={[1, 2]}
      camera={{ position: VIEWS.overview.pos, fov: 38, near: 0.5, far: 90000 }}
      gl={{ antialias: true, logarithmicDepthBuffer: true }}
      onCreated={({ gl }) => { gl.toneMapping = THREE.ACESFilmicToneMapping; gl.toneMappingExposure = 0.85 }}>
      <SunAndSky scene={scene} />
      <Suspense fallback={null}>
        <World night={night} scene={scene} />
      </Suspense>
      <NightLights scene={scene} />
      <Ground />
      <Frames />
      <Panels scene={scene} />
      <PowerFlow scene={scene} />
      <Equipment hot={hot} />
      <WeatherMast scene={scene} />
      <Hardware scene={scene} />
      <HoverTag scene={scene} inverterRow={inverterRow} />
      <Weather scene={scene} />
      {open.map((a, i) => <AlarmMarker key={a.id} alarm={a} i={i} />)}
      <OrbitControls makeDefault target={VIEWS.overview.target} maxPolarAngle={Math.PI / 2.03} minDistance={8} maxDistance={4000} enableDamping dampingFactor={0.08} />
      <CameraRig view={view} />
      <RendererToneMapping fx={fx} />
      {fx && <Effects />}
    </Canvas>
  )
}
