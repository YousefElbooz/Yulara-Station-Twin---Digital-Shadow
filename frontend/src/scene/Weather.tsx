// Weather you can see. Every effect is driven by a number from /api/scene:
//   wind swooshes  <- weather.wind_ms, wind_from_deg   (style: curly strokes that draw on and fade, like a wind icon)
//   dust in the air <- weather.wind_ms above ~5 m/s (strong enough to lift sand); swooshes turn sandy too
//   rain           <- weather.rain_mm_h (ERA5, hourly) ; nothing falls when ERA5 says 0
// Motion is 6x real wind speed so it reads on a 270 m site (said in the HUD).
import { Line } from '@react-three/drei'
import { useFrame } from '@react-three/fiber'
import { useMemo, useRef } from 'react'
import * as THREE from 'three'
import type { Scene } from '../api'
import { CENTER, FENCE } from './layout'

const DEG = Math.PI / 180
export const WIND_VIS = 6
const AREA = { x0: FENCE.x0 - 140, x1: FENCE.x1 + 140, z0: FENCE.z0 - 120, z1: FENCE.z1 + 120 }

/** Smoothed wind as a vector the air moves TOWARD (x east, z south), plus speed. */
function useWind(scene: Scene | null) {
  const w = useRef({ dx: 1, dz: 0, speed: 0 })
  useFrame((_, dt) => {
    const ms = scene?.weather.wind_ms ?? 0
    const to = ((scene?.weather.wind_from_deg ?? 0) + 180) * DEG
    const a = 1 - Math.exp(-dt * 1.2)
    w.current.dx += (Math.sin(to) - w.current.dx) * a
    w.current.dz += (-Math.cos(to) - w.current.dz) * a
    const n = Math.hypot(w.current.dx, w.current.dz) || 1
    w.current.dx /= n; w.current.dz /= n
    w.current.speed += (ms - w.current.speed) * a
  })
  return w
}

// ------------------------------------------------------------------ curly wind strokes
/** One stroke in its own 2D frame: u along the wind, v across. A gentle wave, then a curl at the head. */
function strokePoints(len: number, curlR: number, wave: number, turns: number, flip: number) {
  const pts: [number, number][] = []
  const N = 34
  for (let i = 0; i <= N; i++) { // wavy body
    const s = i / N
    pts.push([-len + s * len, flip * wave * Math.sin(s * Math.PI * 1.3) * (1 - s * 0.4)])
  }
  // curl: spiral that turns back over the stroke, radius shrinking toward the centre
  const cx = 0, cy = flip * curlR
  const M = 40
  for (let i = 1; i <= M; i++) {
    const s = i / M
    const ang = -Math.PI / 2 + s * turns * Math.PI * 2
    const r = curlR * (1 - s * 0.72)
    pts.push([cx + Math.cos(ang) * r, cy + flip * Math.sin(ang) * r])
  }
  return pts
}

interface Swoosh { pts: [number, number, number][]; len: number; base: THREE.Vector3; age: number; life: number; color: string; width: number; tilt: number }

const N_SWOOSH = 34
function WindSwooshes({ scene }: { scene: Scene | null }) {
  const wind = useWind(scene)
  const groups = useRef<(THREE.Group | null)[]>([])
  const lines = useRef<(THREE.Object3D | null)[]>([])
  const items = useMemo<Swoosh[]>(() => Array.from({ length: N_SWOOSH }, (_, i) => {
    const len = 18 + Math.random() * 30
    const curlR = 2.5 + Math.random() * 4
    const p2 = strokePoints(len, curlR, 1.5 + Math.random() * 3, 0.9 + Math.random() * 0.5, Math.random() < 0.5 ? 1 : -1)
    const pts = p2.map(([u, v]) => [u, v, 0] as [number, number, number])
    let L = 0
    for (let k = 1; k < pts.length; k++) L += Math.hypot(pts[k][0] - pts[k - 1][0], pts[k][1] - pts[k - 1][1])
    return {
      pts, len: L, base: new THREE.Vector3(), age: Math.random() * 6, life: 4 + Math.random() * 3,
      color: i % 3 === 0 ? '#6fa3bf' : '#a3cbdc', width: 2.2 + Math.random() * 1.6, tilt: 0.35 + Math.random() * 0.6,
    }
  }), [])
  const spawn = (s: Swoosh) => {
    s.base.set(THREE.MathUtils.randFloat(AREA.x0, AREA.x1), 4 + Math.random() * 24, THREE.MathUtils.randFloat(AREA.z0, AREA.z1))
    s.age = 0
    s.life = 3.5 + Math.random() * 3
  }
  useMemo(() => items.forEach(spawn), [items])

  useFrame((_, dt) => {
    const w = wind.current
    const active = Math.round(THREE.MathUtils.clamp(4 + w.speed * 4, 0, N_SWOOSH)) // more strokes in stronger wind
    const dustT = THREE.MathUtils.clamp((w.speed - 5) / 6, 0, 1)
    const yaw = Math.atan2(-w.dz, w.dx) // rotate the stroke's u axis onto the wind direction
    items.forEach((s, i) => {
      const g = groups.current[i], l = lines.current[i]
      if (!g || !l) return
      s.age += dt
      if (s.age > s.life) spawn(s)
      const visible = i < active && w.speed > 0.3
      g.visible = visible
      if (!visible) return
      // travel downwind at (scaled) wind speed
      s.base.x += w.dx * w.speed * WIND_VIS * dt
      s.base.z += w.dz * w.speed * WIND_VIS * dt
      if (s.base.x < AREA.x0 - 60 || s.base.x > AREA.x1 + 60 || s.base.z < AREA.z0 - 60 || s.base.z > AREA.z1 + 60) spawn(s)
      g.position.copy(s.base)
      g.rotation.set(0, yaw, 0)
      g.children[0].rotation.set(s.tilt, 0, 0) // tip the stroke's plane so it reads from above and from the side
      // draw on from the tail, then erase from the tail: the curl is the last thing to go
      const t = s.age / s.life
      const m = (l as unknown as { material: THREE.Material & { dashOffset: number; opacity: number; color: THREE.Color } }).material
      m.dashOffset = s.len * (1 - 2 * THREE.MathUtils.smootherstep(t, 0, 1))
      m.opacity = 0.9 * Math.min(1, t * 6, (1 - t) * 4)
      m.color.set(s.color).lerp(new THREE.Color('#d9a066'), dustT * (i % 2 === 0 ? 0.9 : 0.5))
    })
  })
  return (
    <group>
      {items.map((s, i) => (
        <group key={i} ref={(el) => { groups.current[i] = el }}>
          <group>
            <Line ref={(el) => { lines.current[i] = el as unknown as THREE.Object3D }} points={s.pts} color={s.color} lineWidth={s.width}
              dashed dashSize={s.len} gapSize={s.len * 2} dashScale={1} transparent opacity={0} depthWrite={false} />
          </group>
        </group>
      ))}
    </group>
  )
}

// ------------------------------------------------------------------ dust carried in the wind
const N_DUST = 3500
function Dust({ scene }: { scene: Scene | null }) {
  const wind = useWind(scene)
  const ref = useRef<THREE.Points>(null!)
  const data = useMemo(() => {
    const pos = new Float32Array(N_DUST * 3), ph = new Float32Array(N_DUST)
    for (let i = 0; i < N_DUST; i++) {
      pos[i * 3] = THREE.MathUtils.randFloat(AREA.x0, AREA.x1)
      pos[i * 3 + 1] = Math.random() ** 2.2 * 14
      pos[i * 3 + 2] = THREE.MathUtils.randFloat(AREA.z0, AREA.z1)
      ph[i] = Math.random() * 100
    }
    return { pos, ph }
  }, [])
  const wrap = (v: number, a: number, b: number) => (v < a ? v + (b - a) : v > b ? v - (b - a) : v)
  useFrame(({ clock }, dt) => {
    const w = wind.current
    const dustT = THREE.MathUtils.clamp((w.speed - 5) / 6, 0, 1) // sand lifts from ~5 m/s
    const mat = ref.current.material as THREE.PointsMaterial
    mat.opacity = dustT * 0.75
    ref.current.visible = dustT > 0.01
    if (!ref.current.visible) return
    const t = clock.elapsedTime, d = Math.min(dt, 0.05)
    const { pos, ph } = data
    for (let i = 0; i < N_DUST; i++) {
      // drift downwind + swirl (eddies) so the dust rolls through the air like the wind strokes
      const sw = Math.sin(t * 1.3 + ph[i]) * 2.2, sw2 = Math.cos(t * 1.1 + ph[i] * 1.7)
      pos[i * 3] = wrap(pos[i * 3] + (w.dx * w.speed * WIND_VIS * (0.8 + (i % 5) * 0.08) - w.dz * sw) * d, AREA.x0, AREA.x1)
      pos[i * 3 + 2] = wrap(pos[i * 3 + 2] + (w.dz * w.speed * WIND_VIS * (0.8 + (i % 5) * 0.08) + w.dx * sw) * d, AREA.z0, AREA.z1)
      pos[i * 3 + 1] = THREE.MathUtils.clamp(pos[i * 3 + 1] + sw2 * 1.6 * d, 0.1, 16)
    }
    ;(ref.current.geometry.attributes.position as THREE.BufferAttribute).needsUpdate = true
  })
  return (
    <points ref={ref} frustumCulled={false}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[data.pos, 3]} />
      </bufferGeometry>
      <pointsMaterial color="#d49a62" size={0.55} sizeAttenuation transparent opacity={0} depthWrite={false} />
    </points>
  )
}

// ------------------------------------------------------------------ rain
const N_RAIN = 9000
function Rain({ scene }: { scene: Scene | null }) {
  const wind = useWind(scene)
  const ref = useRef<THREE.LineSegments>(null!)
  const box = { x0: CENTER.x - 320, x1: CENTER.x + 320, z0: CENTER.z - 260, z1: CENTER.z + 260, top: 90 }
  const data = useMemo(() => {
    const head = new Float32Array(N_RAIN * 3), seg = new Float32Array(N_RAIN * 6)
    for (let i = 0; i < N_RAIN; i++) {
      head[i * 3] = THREE.MathUtils.randFloat(box.x0, box.x1)
      head[i * 3 + 1] = Math.random() * box.top
      head[i * 3 + 2] = THREE.MathUtils.randFloat(box.z0, box.z1)
    }
    return { head, seg }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  const cur = useRef(0)
  useFrame((_, dt) => {
    const mm = scene?.weather.rain_mm_h ?? 0
    // 0.1 mm/h -> a few drops, ~2 mm/h (the wettest ERA5 hours at Yulara) -> full
    const target = mm < 0.05 ? 0 : THREE.MathUtils.clamp(0.1 + Math.log10(1 + mm * 4) / Math.log10(9), 0, 1)
    cur.current += (target - cur.current) * (1 - Math.exp(-dt * 1.5))
    const k = cur.current
    ref.current.visible = k > 0.01
    if (!ref.current.visible) return
    const n = Math.floor(N_RAIN * k)
    const w = wind.current, d = Math.min(dt, 0.05)
    const fall = 9 // m/s, typical raindrop speed (real time, not scaled)
    const dx = w.dx * w.speed * 0.9, dz = w.dz * w.speed * 0.9 // drops drift with the real wind
    const { head, seg } = data
    for (let i = 0; i < n; i++) {
      head[i * 3] += dx * d; head[i * 3 + 2] += dz * d; head[i * 3 + 1] -= fall * d
      if (head[i * 3 + 1] < 0) {
        head[i * 3] = THREE.MathUtils.randFloat(box.x0, box.x1); head[i * 3 + 1] = box.top; head[i * 3 + 2] = THREE.MathUtils.randFloat(box.z0, box.z1)
      }
      const x = head[i * 3], y = head[i * 3 + 1], z = head[i * 3 + 2]
      const s = 0.12 // streak = 0.12 s of motion (motion blur)
      seg.set([x, y, z, x - dx * s, y + fall * s, z - dz * s], i * 6)
    }
    const g = ref.current.geometry
    g.setDrawRange(0, n * 2)
    ;(g.attributes.position as THREE.BufferAttribute).needsUpdate = true
    ;(ref.current.material as THREE.LineBasicMaterial).opacity = 0.25 + 0.3 * k
  })
  return (
    <lineSegments ref={ref} frustumCulled={false}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[data.seg, 3]} />
      </bufferGeometry>
      <lineBasicMaterial color="#cfdbe6" transparent opacity={0.4} depthWrite={false} />
    </lineSegments>
  )
}

export default function Weather({ scene }: { scene: Scene | null }) {
  return (
    <group>
      <WindSwooshes scene={scene} />
      <Dust scene={scene} />
      <Rain scene={scene} />
    </group>
  )
}
