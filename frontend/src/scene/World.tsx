// The land around the station. Real things at real places where we know them, marked approximate where not:
//   Uluru       25.345°S 131.036°E -> ~12.6 km SSE of the plant, 348 m above the plain (shape stylised)
//   Kata Tjuta  25.30°S 130.733°E  -> ~26 km WSW, highest dome 546 m above the plain (domes stylised)
//   Desert Gardens Hotel ~270 m west of the plant, Yulara Drive to the south: positions approximate
//   Ground: red sand with spinifex and desert oaks (typical of the Yulara dune field), not mapped plant by plant.
// Textures: Poly Haven, CC0 (public/textures/ATTRIBUTION.md). Nothing from Esri imagery is used.
import { useTexture } from '@react-three/drei'
import { useFrame } from '@react-three/fiber'
import { useLayoutEffect, useMemo, useRef } from 'react'
import * as THREE from 'three'
import type { Scene } from '../api'
import { hov } from './hover'
import { CENTER, FENCE } from './layout'

const LAT0 = -25.2427, LON0 = 130.982
/** local metres (x east, z south) of a lat/lon, around the plant */
export function enu(lat: number, lon: number) {
  const x = (lon - LON0) * 111320 * Math.cos((LAT0 * Math.PI) / 180)
  const z = -(lat - LAT0) * 110950
  return { x, z }
}
export const ULURU = { ...enu(-25.345, 131.036), height: 348, length: 3600, width: 1900 }
export const KATA_TJUTA = { ...enu(-25.30, 130.733), height: 546 }
export const HOTEL = { x: -560, z: 40, approximate: true }
export const ROAD_Z = FENCE.z1 + 70

// ------------------------------------------------------------------ noise (deterministic)
function hash(x: number, y: number) {
  const s = Math.sin(x * 127.1 + y * 311.7) * 43758.5453
  return s - Math.floor(s)
}
function vnoise(x: number, y: number) {
  const xi = Math.floor(x), yi = Math.floor(y), xf = x - xi, yf = y - yi
  const u = xf * xf * (3 - 2 * xf), v = yf * yf * (3 - 2 * yf)
  const a = hash(xi, yi), b = hash(xi + 1, yi), c = hash(xi, yi + 1), d = hash(xi + 1, yi + 1)
  return a + (b - a) * u + (c - a) * v + (a - b - c + d) * u * v
}
function fbm(x: number, y: number, oct = 4) {
  let s = 0, amp = 0.5, f = 1
  for (let i = 0; i < oct; i++) { s += amp * vnoise(x * f, y * f); amp *= 0.5; f *= 2 }
  return s
}
/** Gentle dune swell, flat (0) inside a pad around the plant, hotel and road. */
export function groundHeight(x: number, z: number) {
  const dx = Math.max(0, Math.abs(x - CENTER.x) - 230), dz = Math.max(0, Math.abs(z - CENTER.z) - 120)
  const d = Math.hypot(dx, dz)
  const pad = THREE.MathUtils.smoothstep(d, 0, 260)
  const hotel = THREE.MathUtils.smoothstep(Math.hypot(x - HOTEL.x, z - HOTEL.z), 120, 260)
  const road = THREE.MathUtils.smoothstep(Math.abs(z - ROAD_Z), 10, 60)
  // Yulara's dunes run roughly east-west, a few metres high, a few hundred metres apart
  const dune = Math.max(0, Math.sin(z / 140 + fbm(x / 600, z / 600) * 3)) ** 2 * 7
  return (dune + fbm(x / 250, z / 250) * 4) * pad * hotel * road
}

function useRepeat<T extends THREE.Texture | THREE.Texture[]>(tex: T, repeat: number, srgbFirst = true) {
  useLayoutEffect(() => {
    const list = (Array.isArray(tex) ? tex : [tex]) as THREE.Texture[]
    list.forEach((t, i) => {
      t.wrapS = t.wrapT = THREE.RepeatWrapping
      t.repeat.set(repeat, repeat)
      t.anisotropy = 8
      t.colorSpace = i === 0 && srgbFirst ? THREE.SRGBColorSpace : THREE.NoColorSpace
      t.needsUpdate = true
    })
  }, [tex, repeat, srgbFirst])
  return tex
}

// ------------------------------------------------------------------ terrain
function Terrain() {
  const sand = useRepeat(useTexture(['/textures/red_sand_diff_1k.jpg', '/textures/red_sand_nor_gl_1k.jpg', '/textures/red_sand_rough_1k.jpg']), 900)
  const gravel = useRepeat(useTexture(['/textures/gravelly_sand_diff_1k.jpg', '/textures/gravelly_sand_nor_gl_1k.jpg', '/textures/gravelly_sand_rough_1k.jpg']), 1)
  const asphalt = useRepeat(useTexture(['/textures/asphalt_02_diff_1k.jpg', '/textures/asphalt_02_nor_gl_1k.jpg', '/textures/asphalt_02_rough_1k.jpg']), 1)

  const SIZE = 6000, SEG = 300
  const geo = useMemo(() => {
    const g = new THREE.PlaneGeometry(SIZE, SIZE, SEG, SEG)
    g.rotateX(-Math.PI / 2)
    const p = g.attributes.position as THREE.BufferAttribute
    const col = new Float32Array(p.count * 3), c = new THREE.Color()
    for (let i = 0; i < p.count; i++) {
      const x = p.getX(i) + CENTER.x, z = p.getZ(i) + CENTER.z
      const h = groundHeight(x, z)
      p.setY(i, h)
      // break up the texture tiling: dune crests paler and orange, swales darker and redder, plus broad patches
      const patch = fbm(x / 180 + 11, z / 180 + 7)
      const crest = THREE.MathUtils.clamp(h / 9, 0, 1)
      c.setRGB(0.86 + crest * 0.14 + (patch - 0.5) * 0.18, 0.78 + crest * 0.16 + (patch - 0.5) * 0.14, 0.74 + crest * 0.1 + (patch - 0.5) * 0.1)
      c.toArray(col, i * 3)
    }
    g.setAttribute('color', new THREE.BufferAttribute(col, 3))
    g.computeVertexNormals()
    return g
  }, [])
  const fw = FENCE.x1 - FENCE.x0, fd = FENCE.z1 - FENCE.z0
  useLayoutEffect(() => {
    gravel.forEach((t) => t.repeat.set(fw / 5, fd / 5))
    asphalt.forEach((t) => t.repeat.set(6000 / 12, 1))
  }, [gravel, asphalt, fw, fd])

  return (
    <group>
      {/* near ground: textured red sand with dunes */}
      <mesh geometry={geo} position={[CENTER.x, -0.05, CENTER.z]} receiveShadow>
        <meshStandardMaterial map={sand[0]} normalMap={sand[1]} roughnessMap={sand[2]} color="#ff9f78" vertexColors normalScale={new THREE.Vector2(1.4, 1.4)} />
      </mesh>
      {/* far plain out to the horizon (fog blends it) */}
      <mesh rotation-x={-Math.PI / 2} position={[CENTER.x, -0.6, CENTER.z]}>
        <ringGeometry args={[2900, 60000, 64, 1]} />
        <meshStandardMaterial color="#a8532e" roughness={1} />
      </mesh>
      {/* graded gravel inside the fence */}
      <mesh rotation-x={-Math.PI / 2} position={[(FENCE.x0 + FENCE.x1) / 2, 0.02, (FENCE.z0 + FENCE.z1) / 2]} receiveShadow>
        <planeGeometry args={[fw, fd]} />
        <meshStandardMaterial map={gravel[0]} normalMap={gravel[1]} roughnessMap={gravel[2]} color="#e8b596" />
      </mesh>
      {/* Yulara Drive (approximate line) */}
      <mesh rotation-x={-Math.PI / 2} position={[CENTER.x, 0.04, ROAD_Z]} receiveShadow {...hov('road')}>
        <planeGeometry args={[6000, 9]} />
        <meshStandardMaterial map={asphalt[0]} normalMap={asphalt[1]} roughnessMap={asphalt[2]} color="#8d8a88" />
      </mesh>
      {/* centre line */}
      <mesh rotation-x={-Math.PI / 2} position={[CENTER.x, 0.06, ROAD_Z]}>
        <planeGeometry args={[6000, 0.15]} />
        <meshBasicMaterial color="#e9e3d0" transparent opacity={0.7} />
      </mesh>
    </group>
  )
}

// ------------------------------------------------------------------ plants sway in the wind
// One set of uniforms shared by every plant material, updated each frame from scene.weather (real wind).
type SwayUniforms = { uTime: { value: number }; uWindDir: { value: THREE.Vector2 }; uWindSpeed: { value: number } }
function makeSway(): SwayUniforms {
  return { uTime: { value: 0 }, uWindDir: { value: new THREE.Vector2(1, 0) }, uWindSpeed: { value: 0 } }
}
/** Bend instanced plants downwind: the top moves most, the base stays put; slow gusts + fast leaf flutter. */
function swayShader(u: SwayUniforms, amp: number) {
  return (shader: THREE.WebGLProgramParametersWithUniforms) => {
    Object.assign(shader.uniforms, u)
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', `#include <common>
uniform float uTime; uniform vec2 uWindDir; uniform float uWindSpeed;`)
      .replace('#include <project_vertex>', `
vec4 mvPosition = vec4( transformed, 1.0 );
#ifdef USE_INSTANCING
  mvPosition = instanceMatrix * mvPosition;
  float ph = instanceMatrix[3].x * 0.071 + instanceMatrix[3].z * 0.053;
#else
  float ph = 0.0;
#endif
float hgt = clamp( ( transformed.y + 1.0 ) * 0.5, 0.0, 1.0 );
hgt *= hgt;
float gust = 0.55 + 0.45 * sin( uTime * 0.55 + ph * 0.7 ) * sin( uTime * 0.23 + ph );
float sway = 0.75 + 0.25 * sin( uTime * ( 1.1 + uWindSpeed * 0.09 ) + ph );
float lean = uWindSpeed * 0.055 * gust * sway;
float flutter = sin( uTime * ( 7.0 + uWindSpeed ) + ph * 5.0 + transformed.x * 3.0 + transformed.z * 2.0 ) * 0.012 * uWindSpeed;
mvPosition.xz += uWindDir * ( lean * hgt * ${amp.toFixed(2)} ) + vec2( flutter, -flutter * 0.6 ) * hgt * ${amp.toFixed(2)};
mvPosition.y -= lean * lean * hgt * ${(amp * 0.15).toFixed(3)};
mvPosition = modelViewMatrix * mvPosition;
gl_Position = projectionMatrix * mvPosition;`)
  }
}

// ------------------------------------------------------------------ plants
function keepOut(x: number, z: number) {
  const inFence = x > FENCE.x0 - 8 && x < FENCE.x1 + 8 && z > FENCE.z0 - 8 && z < FENCE.z1 + 8
  const onRoad = Math.abs(z - ROAD_Z) < 12
  const atHotel = Math.abs(x - HOTEL.x) < 110 && Math.abs(z - HOTEL.z) < 90
  return inFence || onRoad || atHotel
}

function Spinifex({ sway }: { sway: SwayUniforms }) {
  const onCompile = useMemo(() => swayShader(sway, 0.9), [sway])
  const N = 6000
  const ref = useRef<THREE.InstancedMesh>(null!)
  const colors = useMemo(() => new Float32Array(N * 3).fill(1), [])
  useLayoutEffect(() => {
    const o = new THREE.Object3D(), c = new THREE.Color()
    let k = 0, i = 0
    while (k < N && i < N * 4) {
      i++
      const r = 15 + Math.sqrt(hash(i, 1)) * 1400, a = hash(i, 2) * Math.PI * 2
      const x = CENTER.x + Math.cos(a) * r * 1.3, z = CENTER.z + Math.sin(a) * r
      if (keepOut(x, z)) continue
      // spinifex grows in clumps: thin it with noise
      if (fbm(x / 60, z / 60) < 0.42) continue
      const s = 0.5 + hash(i, 3) * 1.1
      o.position.set(x, groundHeight(x, z) - 0.05, z)
      o.scale.set(s * (1 + hash(i, 4) * 0.6), s * 0.55, s * (1 + hash(i, 5) * 0.6))
      o.rotation.set(0, hash(i, 6) * 6.3, 0)
      o.updateMatrix()
      ref.current.setMatrixAt(k, o.matrix)
      c.setHSL(0, 0, 0.8 + hash(i, 8) * 0.4) // brightness variation around the base colour
      c.toArray(colors, k * 3)
      k++
    }
    ref.current.count = k
    ref.current.instanceMatrix.needsUpdate = true
    ref.current.instanceColor!.needsUpdate = true
  }, [])
  return (
    <instancedMesh ref={ref} args={[undefined, undefined, N]} castShadow receiveShadow>
      <icosahedronGeometry args={[1, 1]} />
      <instancedBufferAttribute attach="instanceColor" args={[colors, 3]} />
      <meshStandardMaterial color="#9a9452" roughness={0.95} flatShading onBeforeCompile={onCompile} customProgramCacheKey={() => 'sway-spinifex'} />
    </instancedMesh>
  )
}

function DesertOaks({ sway }: { sway: SwayUniforms }) {
  const onCompile = useMemo(() => swayShader(sway, 2.6), [sway])
  const N = 320
  const trunk = useRef<THREE.InstancedMesh>(null!)
  const crown = useRef<THREE.InstancedMesh>(null!)
  const colors = useMemo(() => new Float32Array(N * 3).fill(1), [])
  useLayoutEffect(() => {
    const o = new THREE.Object3D(), c = new THREE.Color()
    let k = 0, i = 0
    while (k < N && i < N * 10) {
      i++
      const r = 60 + Math.sqrt(hash(i, 11)) * 1500, a = hash(i, 12) * Math.PI * 2
      const x = CENTER.x + Math.cos(a) * r * 1.3, z = CENTER.z + Math.sin(a) * r
      if (keepOut(x, z)) continue
      const h = 5 + hash(i, 13) * 9 // desert oaks: 5-14 m
      const y = groundHeight(x, z)
      o.position.set(x, y + h * 0.35, z); o.scale.set(0.25 + h * 0.015, h * 0.7, 0.25 + h * 0.015); o.rotation.set(0, 0, 0); o.updateMatrix()
      trunk.current.setMatrixAt(k, o.matrix)
      // mature oaks: wide, droopy, grey-green crown; young ones: tall narrow column
      const young = hash(i, 14) < 0.3
      const w = young ? 1.2 + h * 0.08 : 2.5 + h * 0.35
      o.position.set(x, y + (young ? h * 0.55 : h * 0.78), z)
      o.scale.set(w, young ? h * 0.5 : h * 0.3, w * (0.8 + hash(i, 15) * 0.4)); o.rotation.set(0, hash(i, 16) * 6.3, 0); o.updateMatrix()
      crown.current.setMatrixAt(k, o.matrix)
      c.setHSL(0, 0, 0.8 + hash(i, 18) * 0.4)
      c.toArray(colors, k * 3)
      k++
    }
    trunk.current.count = crown.current.count = k
    trunk.current.instanceMatrix.needsUpdate = crown.current.instanceMatrix.needsUpdate = true
    crown.current.instanceColor!.needsUpdate = true
  }, [])
  return (
    <group>
      <instancedMesh ref={trunk} args={[undefined, undefined, N]} castShadow>
        <cylinderGeometry args={[0.5, 1, 1, 6]} />
        <meshStandardMaterial color="#3b2e26" roughness={1} />
      </instancedMesh>
      <instancedMesh ref={crown} args={[undefined, undefined, N]} castShadow receiveShadow {...hov('oak')}>
        <dodecahedronGeometry args={[1, 1]} />
        <instancedBufferAttribute attach="instanceColor" args={[colors, 3]} />
        <meshStandardMaterial color="#4c5a3c" roughness={0.9} flatShading onBeforeCompile={onCompile} customProgramCacheKey={() => 'sway-oak'} />
      </instancedMesh>
    </group>
  )
}

// ------------------------------------------------------------------ hotel (approximate)
function Hotel({ night }: { night: boolean }) {
  const blocks: [number, number, number, number, number][] = [ // x, z, w, d, h
    [-60, -40, 70, 14, 7], [-60, 0, 70, 14, 7], [-60, 40, 70, 14, 7], [30, -30, 40, 16, 8], [30, 25, 44, 18, 9], [-5, 70, 30, 12, 5],
  ]
  return (
    <group position={[HOTEL.x, 0, HOTEL.z]} {...hov('hotel')}>
      {blocks.map(([x, z, w, d, h], i) => (
        <group key={i} position={[x, 0, z]}>
          <mesh position={[0, h / 2, 0]} castShadow receiveShadow>
            <boxGeometry args={[w, h, d]} />
            <meshStandardMaterial color="#e8dcc8" roughness={0.85} emissive="#ffcf7a" emissiveIntensity={night ? 0.18 : 0} />
          </mesh>
          {/* corrugated roof, slightly overhanging */}
          <mesh position={[0, h + 0.4, 0]} castShadow>
            <boxGeometry args={[w + 2, 0.6, d + 2]} />
            <meshStandardMaterial color="#6c7a76" metalness={0.5} roughness={0.5} />
          </mesh>
        </group>
      ))}
      {/* pool */}
      <mesh rotation-x={-Math.PI / 2} position={[-5, 0.08, 50]}>
        <planeGeometry args={[20, 9]} />
        <meshStandardMaterial color="#3ec6d6" roughness={0.1} metalness={0.2} />
      </mesh>
    </group>
  )
}

// ------------------------------------------------------------------ Uluru and Kata Tjuta (stylised shapes at real positions)
function useRock() {
  const rock = useRepeat(useTexture(['/textures/rock_boulder_dry_diff_1k.jpg', '/textures/rock_boulder_dry_nor_gl_1k.jpg', '/textures/rock_boulder_dry_rough_1k.jpg']), 14)
  return rock
}

function Uluru() {
  const rock = useRock()
  const geo = useMemo(() => {
    const g = new THREE.PlaneGeometry(2, 2, 220, 130)
    g.rotateX(-Math.PI / 2)
    const p = g.attributes.position as THREE.BufferAttribute
    for (let i = 0; i < p.count; i++) {
      const u = p.getX(i), v = p.getZ(i)
      const ang = Math.atan2(v, u)
      // slightly lumpy outline, steep walls, rounded flat-ish top
      const rim = 1 + 0.06 * Math.sin(ang * 3 + 1) + 0.04 * Math.sin(ang * 7)
      const r = Math.hypot(u, v) / rim
      let h = r < 1 ? Math.pow(Math.max(0, 1 - Math.pow(r, 5)), 0.45) : -0.02
      h *= 0.94 + 0.06 * fbm(u * 2 + 5, v * 2 + 5)
      // shallow vertical flutes on the walls (the rock's characteristic gullies)
      const wall = THREE.MathUtils.smoothstep(r, 0.7, 1)
      h -= wall * 0.025 * Math.max(0, Math.sin(ang * 46 + fbm(u * 4, v * 4) * 4))
      p.setY(i, h)
    }
    g.computeVertexNormals()
    return g
  }, [])
  return (
    <mesh geometry={geo} position={[ULURU.x, -2, ULURU.z]} scale={[ULURU.length / 2, ULURU.height, ULURU.width / 2]} rotation-y={0.25} {...hov('uluru')}>
      <meshStandardMaterial map={rock[0]} normalMap={rock[1]} roughnessMap={rock[2]} color="#ff7a3c" />
    </mesh>
  )
}

function KataTjuta() {
  const rock = useRock()
  const domes = useMemo(() => {
    const d: [number, number, number, number][] = [] // dx, dz, radius, height
    for (let i = 0; i < 26; i++) {
      const a = hash(i, 31) * Math.PI * 2, r = Math.sqrt(hash(i, 32)) * 2300
      const h = i === 0 ? KATA_TJUTA.height : 120 + hash(i, 33) * 330
      d.push([i === 0 ? 0 : Math.cos(a) * r, i === 0 ? 0 : Math.sin(a) * r, h * (1.0 + hash(i, 34) * 0.6), h])
    }
    return d
  }, [])
  const ref = useRef<THREE.InstancedMesh>(null!)
  const geo = useMemo(() => {
    const g = new THREE.SphereGeometry(1, 48, 24, 0, Math.PI * 2, 0, Math.PI / 2)
    const p = g.attributes.position as THREE.BufferAttribute
    for (let i = 0; i < p.count; i++) { const y = p.getY(i); p.setY(i, Math.pow(y, 0.7)) } // steep-sided domes
    g.computeVertexNormals()
    return g
  }, [])
  useLayoutEffect(() => {
    const o = new THREE.Object3D()
    domes.forEach(([dx, dz, r, h], i) => {
      o.position.set(KATA_TJUTA.x + dx, -3, KATA_TJUTA.z + dz); o.scale.set(r, h, r * (0.7 + hash(i, 35) * 0.5)); o.rotation.set(0, hash(i, 36) * 6.3, 0)
      o.updateMatrix(); ref.current.setMatrixAt(i, o.matrix)
    })
    ref.current.instanceMatrix.needsUpdate = true
  }, [domes])
  return (
    <instancedMesh ref={ref} args={[geo, undefined, domes.length]} {...hov('kata')}>
      <meshStandardMaterial map={rock[0]} normalMap={rock[1]} roughnessMap={rock[2]} color="#e8673a" />
    </instancedMesh>
  )
}

const DEG = Math.PI / 180
export default function World({ night, scene }: { night: boolean; scene: Scene | null }) {
  const sway = useMemo(makeSway, [])
  useFrame(({ clock }, dt) => {
    const a = 1 - Math.exp(-dt * 1.2)
    const to = ((scene?.weather.wind_from_deg ?? 0) + 180) * DEG
    sway.uTime.value = clock.elapsedTime
    sway.uWindDir.value.lerp(new THREE.Vector2(Math.sin(to), -Math.cos(to)), a).normalize()
    sway.uWindSpeed.value += ((scene?.weather.wind_ms ?? 0) - sway.uWindSpeed.value) * a
  })
  return (
    <group>
      <Terrain />
      <Spinifex sway={sway} />
      <DesertOaks sway={sway} />
      <Hotel night={night} />
      <Uluru />
      <KataTjuta />
    </group>
  )
}
