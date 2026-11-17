// Thin wrapper around Plotly (no react-plotly.js: it does not support React 19).
import Plotly from 'plotly.js-dist-min'
import { useEffect, useRef } from 'react'

export const C = {
  ink: '#e6ecf5', dim: '#8792a8', grid: 'rgba(135,146,168,0.14)',
  measured: '#30d5c8', physics: '#ffb020', model: '#5ab0ff', alarm: '#ff5c7a', sun: '#ffd60a', dust: '#c9935d',
}

export function baseLayout(extra: Partial<Plotly.Layout> = {}): Partial<Plotly.Layout> {
  return {
    paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
    font: { family: 'JetBrains Mono, monospace', size: 11, color: C.dim },
    margin: { l: 56, r: 16, t: 12, b: 40 },
    xaxis: { gridcolor: C.grid, zerolinecolor: C.grid, linecolor: C.grid },
    yaxis: { gridcolor: C.grid, zerolinecolor: C.grid, linecolor: C.grid },
    legend: { orientation: 'h', y: 1.12, x: 0, font: { color: C.ink, size: 11 } },
    hoverlabel: { bgcolor: '#0d1220', bordercolor: '#2a3550', font: { family: 'JetBrains Mono, monospace', color: C.ink } },
    hovermode: 'x unified',
    ...extra,
  }
}

export default function Plot({ data, layout, height = 300 }: { data: Plotly.Data[]; layout?: Partial<Plotly.Layout>; height?: number }) {
  const el = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!el.current) return
    Plotly.react(el.current, data, { ...baseLayout(), ...layout, height, autosize: true }, { displayModeBar: false, responsive: true })
  }, [data, layout, height])
  useEffect(() => {
    const node = el.current
    return () => { if (node) Plotly.purge(node) }
  }, [])
  return <div ref={el} style={{ width: '100%', height }} />
}
