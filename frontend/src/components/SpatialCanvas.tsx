import { useMemo } from 'react'
import DeckGL from '@deck.gl/react'
import { ScatterplotLayer } from '@deck.gl/layers'
import { OrthographicView } from '@deck.gl/core'
import { useStore } from '../app/store'

const TIER1 = ['#4e79a7','#f28e2b','#e15759','#76b7b2','#59a14f','#edc948','#b07aa1','#ff9da7']
const TIER2 = ['#4e79a7','#a0cbe8','#f28e2b','#ffbe7d','#59a14f','#8cd17d','#b6992d','#f1ce63','#499894','#86bcb6','#e15759','#ff9d9a','#79706e','#bab0ac','#d37295','#fabfd2','#b07aa1','#d4a6c8']
const TIER3 = ['#e63946','#c1121f','#ff4d6d','#fb8500','#ffb347','#f4442e','#ffd60a','#f7b731','#80b918','#c5d86d','#52b788','#2d6a4f','#1b4332','#74c69d','#2ec4b6','#06d6a0','#48cae4','#00b4d8','#4cc9f0','#4895ef','#0077b6','#4361ee','#023e8a','#3a0ca3','#480ca8','#7209b7','#560bad','#8338ec','#9b5de5','#b5179e','#f72585','#e91e8c','#ff99c8','#c77dff','#774936','#9b7451','#d4a373','#8d99ae','#495057','#bcbd22']

function pickPalette(n: number): string[] { return n <= 8 ? TIER1 : n <= 18 ? TIER2 : TIER3 }
function colorForKey(value: string, palette: string[]): [number, number, number] {
  let h = 0; for (let i = 0; i < value.length; i++) h = value.charCodeAt(i) + ((h << 5) - h)
  const hex = palette[Math.abs(h) % palette.length].replace('#', '')
  return [parseInt(hex.slice(0,2),16), parseInt(hex.slice(2,4),16), parseInt(hex.slice(4,6),16)]
}

const spatialView = new OrthographicView({ id: 'spatial-view' })

export default function SpatialCanvas() {
  const { points } = useStore((s) => ({ points: s.points }))

  const spatialPoints = useMemo(() => points.filter((p) => p.sx != null && p.sy != null), [points])

  const initialViewState = useMemo(() => {
    if (spatialPoints.length === 0) return { target: [0, 0, 0], zoom: 0 }
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
    for (const p of spatialPoints) {
      if (p.sx! < minX) minX = p.sx!
      if (p.sx! > maxX) maxX = p.sx!
      if (p.sy! < minY) minY = p.sy!
      if (p.sy! > maxY) maxY = p.sy!
    }
    const cx = (minX + maxX) / 2
    const cy = (minY + maxY) / 2
    const span = Math.max(maxX - minX, maxY - minY, 1)
    return { target: [cx, cy, 0], zoom: Math.log2(600 / span) }
  }, [spatialPoints])

  const palette = useMemo(() => pickPalette(new Set(spatialPoints.map((p) => p.cluster)).size), [spatialPoints])
  const layer = useMemo(
    () =>
      new ScatterplotLayer({
        id: 'spatial-layer',
        data: spatialPoints,
        getPosition: (d: any) => [d.sx, d.sy],
        getFillColor: (d: any) => colorForKey(d.cluster ?? '', palette),
        getRadius: 6,
        radiusUnits: 'pixels',
        pickable: false
      }),
    [spatialPoints, palette]
  )

  if (spatialPoints.length === 0) return null

  return (
    <section className="panel">
      <h2>Spatial View</h2>
      <p className="muted">{spatialPoints.length.toLocaleString()} cells with spatial coordinates</p>
      <div style={{ height: 420, position: 'relative', borderRadius: 6, overflow: 'hidden' }}>
        <DeckGL
          views={[spatialView]}
          initialViewState={initialViewState}
          controller
          layers={[layer]}
          style={{ position: 'absolute', inset: 0 }}
        />
      </div>
    </section>
  )
}
