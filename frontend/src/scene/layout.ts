// Station geometry, from docs/station_facts.md (layout section): Esri imagery (≈1.08 m/px) + OpenStreetMap.
// Coordinates in metres: x = east, y = up, z = south (three.js: north is -z). Row 1 (north edge) is z = 0.
// Lengths are ±5 m. The equipment building and weather mast positions are APPROXIMATE (no ground photos).

export const TILT_DEG = 15
export const MODULE_W = 0.992 // m, across the row (portrait width)
export const MODULE_L = 1.956 // m, up the slope
export const MODULES_TOTAL = 3360
export const ROW_DEPTH_FLAT = 2 * MODULE_L * Math.cos((TILT_DEG * Math.PI) / 180) // ≈ 3.78 m

export interface Row { id: number; block: 'A' | 'B'; x0: number; x1: number; z: number }

const Z = [0, 6.9, 13.8, 20.5, 27.4, 34.3, 41.5, 48.4, 55.5, 62.6, 69.5, 77.0, 84.2, 91.1, 98.3]
const A_LEN = [106, 114, 131, 147, 154, 172, 188, 197, 204]
const B_SPAN: [number, number][] = [[-212, -156], [-220, -173], [-229, -181], [-238, -190], [-246, -197], [-254, -205]]

export const ROWS: Row[] = [
  ...A_LEN.map((len, i) => ({ id: i + 1, block: 'A' as const, x0: -len, x1: 0, z: Z[i] })),
  ...B_SPAN.map(([x0, x1], i) => ({ id: i + 10, block: 'B' as const, x0, x1, z: Z[i + 9] })),
]

/** Modules per row: the measured lengths add up to ~1,710 m (~3,450 modules), so they are scaled to the
 *  official 3,360, keeping each row's share of the length. Two portrait modules deep. */
export function modulesPerRow(): number[] {
  const total = ROWS.reduce((s, r) => s + (r.x1 - r.x0), 0)
  const perLine = MODULES_TOTAL / 2
  const raw = ROWS.map((r) => ((r.x1 - r.x0) / total) * perLine)
  const n = raw.map(Math.floor)
  let left = perLine - n.reduce((a, b) => a + b, 0)
  raw.map((v, i) => [v - Math.floor(v), i] as const).sort((a, b) => b[0] - a[0]).forEach(([, i]) => { if (left-- > 0) n[i]++ })
  return n.map((v) => v * 2)
}

export const CENTER = { x: -127, z: 49 } // middle of the array, for the camera target
export const FENCE = { x0: -262, x1: 7, z0: -12, z1: 104 } // ≈269 × 116 m
export const EQUIPMENT = { x: -97, z: -9, approximate: true }
export const MAST = { x: -128, z: -7, approximate: true }
export const INVERTERS_CALCULATED = 42
