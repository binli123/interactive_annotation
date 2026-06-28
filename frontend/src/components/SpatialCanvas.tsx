import { useMemo } from 'react'
import DeckGL from '@deck.gl/react'
import { ScatterplotLayer } from '@deck.gl/layers'
import { OrthographicView } from '@deck.gl/core'
import type { UmapPoint, PaletteName } from '../app/types'
import { useStore } from '../app/store'

const PALETTES: Record<PaletteName, string[]> = {
  bright: ['#0077b6', '#ef476f', '#06d6a0', '#f4a261', '#6a4c93', '#118ab2', '#8ac926', '#ff595e'],
  earth: ['#355070', '#6d597a', '#b56576', '#e56b6f', '#eaac8b', '#7f5539', '#606c38', '#bc6c25'],
  pastel: ['#7bdff2', '#b2f7ef', '#eff7f6', '#f7d6e0', '#f2b5d4', '#cdb4db', '#ffc8dd', '#bde0fe']
}

function colorForKey(value: string, paletteName: PaletteName): [number, number, number] {
  const palette = PALETTES[paletteName]
  let hash = 0
  for (let i = 0; i < value.length; i++) {
    hash = value.charCodeAt(i) + ((hash << 5) - hash)
  }
  const hex = palette[Math.abs(hash) % palette.length].replace('#', '')
  return [parseInt(hex.slice(0, 2), 16), parseInt(hex.slice(2, 4), 16), parseInt(hex.slice(4, 6), 16)]
}

const spatialView = new OrthographicView({ id: 'spatial-view' })

export default function SpatialCanvas() {
  const { points, paletteName } = useStore((s) => ({
    points: s.points,
    paletteName: s.paletteName
  }))

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

  const layer = useMemo(
    () =>
      new ScatterplotLayer({
        id: 'spatial-layer',
        data: spatialPoints,
        getPosition: (d: UmapPoint) => [d.sx!, d.sy!],
        getFillColor: (d: UmapPoint) => colorForKey(d.cluster ?? '', paletteName),
        getRadius: 6,
        radiusUnits: 'pixels',
        pickable: false
      }),
    [spatialPoints, paletteName]
  )

  if (spatialPoints.length === 0) return null

  return (
    <section className="panel">
      <h2>Spatial View</h2>
      <p className="muted">{spatialPoints.length.toLocaleString()} cells with spatial coordinates</p>
      <div style={{ height: 420, position: 'relative', borderRadius: 6, overflow: 'hidden' }}>
        <DeckGL
          views={spatialView}
          initialViewState={initialViewState}
          controller
          layers={[layer]}
          style={{ position: 'absolute', inset: 0 }}
        />
      </div>
    </section>
  )
}
