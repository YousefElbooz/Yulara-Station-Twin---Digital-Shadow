// Night lighting: light poles across the map (security lights around the plant fence, street lights along
// Yulara Drive, lights around the hotel and at the equipment building). They switch on from the real sun
// elevation (scene.sun.elevation_deg below the horizon), fading in like a photocell.
// The poles' positions are ILLUSTRATIVE: the real lighting layout of the site is not known.
import { useFrame } from '@react-three/fiber'
import { useLayoutEffect, useMemo, useRef } from 'react'
import * as THREE from 'three'
import type { Scene } from '../api'
import { CENTER, EQUIPMENT, FENCE } from './layout'
import { HOTEL, ROAD_Z, groundHeight } from './World'
import { hov } from './hover'

const POLE_H = 7
interface Pole { x: number; z: number; yaw: number; reach: number }

function buildPoles(): Pole[] {
  const p: Pole[] = []
  // 1. security lights every ~35 m, 3 m outside the fence, arm pointing in toward the plant
  const sides: [number, number, number, number, number][] = [
    [FENCE.x0, FENCE.z0 - 3, FENCE.x1, FENCE.z0 - 3, Math.PI / 2],   // north side, arm points south (+z)
    [FENCE.x1 + 3, FENCE.z0, FENCE.x1 + 3, FENCE.z1, Math.PI],       // east side, arm points west
    [FENCE.x1, FENCE.z1 + 3, FENCE.x0, FENCE.z1 + 3, -Math.PI / 2],  // south side, arm points north
    [FENCE.x0 - 3, FENCE.z1, FENCE.x0 - 3, FENCE.z0, 0],             // west side, arm points east
  ]
  sides.forEach(([x0, z0, x1, z1, yaw]) => {
    const len = Math.hypot(x1 - x0, z1 - z0), n = Math.max(1, Math.round(len / 35))
    for (let i = 0; i <= n; i++) p.push({ x: x0 + ((x1 - x0) * i) / n, z: z0 + ((z1 - z0) * i) / n, yaw, reach: 13 })
  })
  // 2. street lights along Yulara Drive, both sides, staggered every 45 m
  for (let x = CENTER.x - 1500; x <= CENTER.x + 1500; x += 45) {
    p.push({ x, z: ROAD_Z - 7, yaw: Math.PI / 2, reach: 13 })
    p.push({ x: x + 22, z: ROAD_Z + 7, yaw: -Math.PI / 2, reach: 13 })
  }
  // 3. around the hotel
  for (let i = 0; i < 12; i++) {
    const a = (i / 12) * Math.PI * 2
    p.push({ x: HOTEL.x + Math.cos(a) * 105, z: HOTEL.z + Math.sin(a) * 85, yaw: a + Math.PI, reach: 12 })
  }
  // 4. at the equipment building
  p.push({ x: EQUIPMENT.x - 7, z: EQUIPMENT.z + 4, yaw: Math.PI / 2, reach: 14 })
  p.push({ x: EQUIPMENT.x + 10, z: EQUIPMENT.z + 4, yaw: Math.PI / 2, reach: 14 })
  return p
}

function poolTexture() {
  const c = document.createElement('canvas'); c.width = c.height = 128
  const g = c.getContext('2d')!
  const grad = g.createRadialGradient(64, 64, 0, 64, 64, 64)
  grad.addColorStop(0, 'rgba(255,214,150,1)')
  grad.addColorStop(0.35, 'rgba(255,190,120,0.55)')
  grad.addColorStop(1, 'rgba(255,170,100,0)')
  g.fillStyle = grad; g.fillRect(0, 0, 128, 128)
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace
  return t
}

export default function NightLights({ scene }: { scene: Scene | null }) {
  const poles = useMemo(buildPoles, [])
  const pool = useMemo(poolTexture, [])
  const poleRef = useRef<THREE.InstancedMesh>(null!)
  const armRef = useRef<THREE.InstancedMesh>(null!)
  const headRef = useRef<THREE.InstancedMesh>(null!)
  const poolRef = useRef<THREE.InstancedMesh>(null!)
  const headMat = useRef<THREE.MeshStandardMaterial>(null!)
  const poolMat = useRef<THREE.MeshBasicMaterial>(null!)
  const lamps = useRef<(THREE.PointLight | null)[]>([])
  const on = useRef(0)

  // a few real lights near the plant so the panels and the building actually catch light
  const real = useMemo(() => [
    { x: EQUIPMENT.x - 7, z: EQUIPMENT.z + 4 }, { x: EQUIPMENT.x + 10, z: EQUIPMENT.z + 4 },
    { x: FENCE.x0 + 40, z: FENCE.z0 - 3 }, { x: FENCE.x1, z: FENCE.z0 + 40 },
    { x: FENCE.x1 - 60, z: FENCE.z1 + 3 }, { x: FENCE.x0 + 100, z: FENCE.z1 + 3 },
  ], [])

  useLayoutEffect(() => {
    const o = new THREE.Object3D()
    poles.forEach((p, i) => {
      const y = groundHeight(p.x, p.z)
      const ax = Math.cos(p.yaw), az = Math.sin(p.yaw)
      o.rotation.set(0, 0, 0); o.scale.set(1, 1, 1)
      o.position.set(p.x, y + POLE_H / 2, p.z); o.updateMatrix(); poleRef.current.setMatrixAt(i, o.matrix)
      o.position.set(p.x + ax * 0.8, y + POLE_H - 0.1, p.z + az * 0.8); o.rotation.set(0, -p.yaw, 0); o.updateMatrix(); armRef.current.setMatrixAt(i, o.matrix)
      o.position.set(p.x + ax * 1.6, y + POLE_H - 0.25, p.z + az * 1.6); o.updateMatrix(); headRef.current.setMatrixAt(i, o.matrix)
      // the lit circle on the ground, a little ahead of the pole in the arm's direction
      o.rotation.set(-Math.PI / 2, 0, 0); o.scale.set(p.reach, p.reach, 1)
      o.position.set(p.x + ax * 3, groundHeight(p.x + ax * 3, p.z + az * 3) + 0.12, p.z + az * 3); o.updateMatrix(); poolRef.current.setMatrixAt(i, o.matrix)
    })
    for (const r of [poleRef, armRef, headRef, poolRef]) r.current.instanceMatrix.needsUpdate = true
  }, [poles])

  useFrame((_, dt) => {
    // photocell: on as the sun goes below the horizon, fully on by 5 degrees below
    const el = scene?.sun.elevation_deg ?? 10
    const target = THREE.MathUtils.clamp((1 - el) / 6, 0, 1)
    on.current += (target - on.current) * (1 - Math.exp(-dt * 1.2))
    const k = on.current
    headMat.current.emissiveIntensity = k * 8
    poolMat.current.opacity = k * 0.42
    poolRef.current.visible = k > 0.01
    lamps.current.forEach((l) => { if (l) { l.intensity = k * 900; l.visible = k > 0.01 } })
  })

  return (
    <group>
      <instancedMesh ref={poleRef} args={[undefined, undefined, poles.length]} castShadow {...hov('light')}>
        <cylinderGeometry args={[0.07, 0.11, POLE_H, 6]} />
        <meshStandardMaterial color="#8d939c" metalness={0.7} roughness={0.45} />
      </instancedMesh>
      <instancedMesh ref={armRef} args={[undefined, undefined, poles.length]}>
        <boxGeometry args={[1.6, 0.07, 0.07]} />
        <meshStandardMaterial color="#8d939c" metalness={0.7} roughness={0.45} />
      </instancedMesh>
      <instancedMesh ref={headRef} args={[undefined, undefined, poles.length]}>
        <boxGeometry args={[0.7, 0.14, 0.3]} />
        <meshStandardMaterial ref={headMat} color="#30343a" emissive="#ffd9a0" emissiveIntensity={0} toneMapped={false} />
      </instancedMesh>
      <instancedMesh ref={poolRef} args={[undefined, undefined, poles.length]} renderOrder={1}>
        <circleGeometry args={[1, 32]} />
        <meshBasicMaterial ref={poolMat} map={pool} color="#ffcf96" transparent opacity={0} depthWrite={false}
          blending={THREE.AdditiveBlending} polygonOffset polygonOffsetFactor={-2} />
      </instancedMesh>
      {real.map((r, i) => (
        <pointLight key={i} ref={(el) => { lamps.current[i] = el }} position={[r.x, POLE_H - 0.5, r.z]}
          color="#ffd2a0" intensity={0} distance={55} decay={2} />
      ))}
    </group>
  )
}
