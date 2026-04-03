import { useEffect, useMemo, useRef, useState } from 'react'
import DeckGL from '@deck.gl/react'
import { OrthographicView } from '@deck.gl/core'
import { PolygonLayer, ScatterplotLayer } from '@deck.gl/layers'
import { useStore } from '../app/store'
import type { PaletteName, PolygonRecord, UmapPoint } from '../app/types'

type ViewMode = 'lineage' | 'global'

type RenderPoint = UmapPoint & {
  annotationLabel: string
  annotationScore?: number
  displayPosition?: [number, number]
}

type RenderPolygon = PolygonRecord & {
  displayVertices: [number, number][]
}

const palettes: Record<PaletteName, string[]> = {
  bright: ['#0077b6', '#ef476f', '#06d6a0', '#f4a261', '#6a4c93', '#118ab2', '#8ac926', '#ff595e'],
  earth: ['#355070', '#6d597a', '#b56576', '#e56b6f', '#eaac8b', '#7f5539', '#606c38', '#bc6c25'],
  pastel: ['#7bdff2', '#b2f7ef', '#eff7f6', '#f7d6e0', '#f2b5d4', '#cdb4db', '#ffc8dd', '#bde0fe']
}

const umapView = new OrthographicView({ id: 'umap-view' })

function colorForKey(value: string, paletteName: PaletteName): [number, number, number] {
  const palette = palettes[paletteName]
  let hash = 0
  for (let index = 0; index < value.length; index += 1) {
    hash = value.charCodeAt(index) + ((hash << 5) - hash)
  }
  const hex = palette[Math.abs(hash) % palette.length]
  const stripped = hex.replace('#', '')
  return [
    parseInt(stripped.slice(0, 2), 16),
    parseInt(stripped.slice(2, 4), 16),
    parseInt(stripped.slice(4, 6), 16)
  ]
}

function fitView(points: UmapPoint[]) {
  if (points.length === 0) {
    return { target: [0, 0, 0], zoom: 0 }
  }
  const xs = points.map((point) => point.x)
  const ys = points.map((point) => point.y)
  const minX = Math.min(...xs)
  const maxX = Math.max(...xs)
  const minY = Math.min(...ys)
  const maxY = Math.max(...ys)
  const cx = (minX + maxX) / 2
  const cy = (minY + maxY) / 2
  const span = Math.max(maxX - minX, maxY - minY, 1)
  const zoom = Math.max(-2, Math.min(8, Math.log2(120 / span) + 2))
  return { target: [cx, cy, 0], zoom }
}

function polygonColor(polygon: PolygonRecord, paletteName: PaletteName): [number, number, number, number] {
  const [r, g, b] = colorForKey(polygon.clusterId || polygon.id, paletteName)
  return [r, g, b, polygon.includeForPropagation ? 220 : 120]
}

function transformVertex(
  vertex: [number, number] | number[],
  center: number[],
  flipHorizontal: boolean,
  flipVertical: boolean
): [number, number] {
  const x = Number(vertex[0])
  const y = Number(vertex[1])
  const cx = Number(center[0] ?? 0)
  const cy = Number(center[1] ?? 0)
  return [
    flipHorizontal ? cx - (x - cx) : x,
    flipVertical ? cy - (y - cy) : y
  ]
}

export default function UmapCanvas({ mode }: { mode: ViewMode }) {
  const frameRef = useRef<HTMLDivElement | null>(null)
  const state = useStore((store) => ({
    points: mode === 'lineage' ? store.points : store.globalPoints,
    polygons: mode === 'lineage' ? store.polygons : [],
    draftVertices: mode === 'lineage' ? store.draftVertices : [],
    isDrawing: mode === 'lineage' ? store.isDrawing : false,
    startDrawing: store.startDrawing,
    stopDrawing: store.stopDrawing,
    addDraftVertex: store.addDraftVertex,
    undoDraftVertex: store.undoDraftVertex,
    finalizeDraftPolygon: store.finalizeDraftPolygon,
    clearDraftPolygon: store.clearDraftPolygon,
    clearPolygons: store.clearPolygons,
    propagationResult: mode === 'lineage' ? store.propagationResult : undefined,
    colorMode: mode === 'lineage' ? store.colorMode : 'cluster',
    clusterVisibility: mode === 'lineage' ? store.clusterVisibility : {},
    geneColorGene: mode === 'lineage' ? store.geneColorGene : undefined,
    pointSize: store.pointSize,
    pointOpacity: store.pointOpacity,
    paletteName: store.paletteName,
    polygonStrokeWidth: store.polygonStrokeWidth,
    flipHorizontal: store.flipHorizontal,
    flipVertical: store.flipVertical,
    globalHighlight: store.globalHighlight
  }))
  const visibleBasePoints = useMemo(
    () =>
      mode === 'lineage'
        ? state.points.filter((point) => {
            if (!point.cluster) {
              return true
            }
            return state.clusterVisibility[point.cluster] ?? true
          })
        : state.points,
    [mode, state.clusterVisibility, state.points]
  )
  const fit = useMemo(() => fitView(visibleBasePoints), [visibleBasePoints])
  const flipCenter = fit.target
  const [viewState, setViewState] = useState<{ target: number[]; zoom: number }>(fit)
  const [frameSize, setFrameSize] = useState({ width: 1, height: 1 })

  useEffect(() => {
    setViewState(fit)
  }, [fit])

  useEffect(() => {
    const node = frameRef.current
    if (!node) {
      return
    }
    const updateSize = () => {
      setFrameSize({
        width: Math.max(node.clientWidth, 1),
        height: Math.max(node.clientHeight, 1)
      })
    }
    updateSize()
    const observer = new ResizeObserver(updateSize)
    observer.observe(node)
    return () => observer.disconnect()
  }, [])

  const propagatedMap = useMemo(() => {
    const lookup = new Map<number, { label: string; score: number }>()
    for (const cell of state.propagationResult?.cells ?? []) {
      lookup.set(cell.index, { label: cell.predicted_label, score: cell.score })
    }
    return lookup
  }, [state.propagationResult])

  const renderPoints: RenderPoint[] = useMemo(
    () =>
      visibleBasePoints.map((point) => {
        const propagated = propagatedMap.get(point.index)
        return {
          ...point,
          annotationLabel: propagated?.label ?? point.current_label ?? 'Unassigned',
          annotationScore: propagated?.score ?? point.current_score ?? undefined
        }
      }),
    [visibleBasePoints, propagatedMap]
  )

  const transformedDraftVertices = useMemo(
    () =>
      state.draftVertices.map((vertex) =>
        transformVertex(vertex, flipCenter, state.flipHorizontal, state.flipVertical)
      ),
    [flipCenter, state.draftVertices, state.flipHorizontal, state.flipVertical]
  )

  const displayPoints: RenderPoint[] = useMemo(
    () =>
      renderPoints.map((point) => ({
        ...point,
        displayPosition: transformVertex([point.x, point.y], flipCenter, state.flipHorizontal, state.flipVertical)
      })),
    [flipCenter, renderPoints, state.flipHorizontal, state.flipVertical]
  )

  const displayPolygons: RenderPolygon[] = useMemo(
    () =>
      state.polygons.map((polygon) => ({
        ...polygon,
        displayVertices: polygon.vertices.map((vertex) =>
          transformVertex(vertex, flipCenter, state.flipHorizontal, state.flipVertical)
        )
      })),
    [flipCenter, state.flipHorizontal, state.flipVertical, state.polygons]
  )

  const pointLayer = useMemo(
    () =>
      new ScatterplotLayer({
        id: `${mode}-umap-points`,
        data: displayPoints as unknown[],
        getPosition: (point: any) => point.displayPosition ?? [point.x, point.y],
        getRadius: () => state.pointSize,
        radiusMinPixels: state.pointSize,
        radiusMaxPixels: state.pointSize * 2.5,
        pickable: true,
        opacity: state.pointOpacity,
        getFillColor: (point: any) => {
          if (mode === 'global' && state.globalHighlight) {
            if (point.is_highlighted) {
              const [r, g, b] = colorForKey(state.globalHighlight.sourceClusterId, state.paletteName)
              return [r, g, b, 255]
            }
            return [178, 182, 188, 110]
          }
          if (state.colorMode === 'gene') {
            const value = Math.max(0, point.gene_expression ?? 0)
            const capped = Math.min(1, value / 4)
            const r = Math.round(248 - capped * 118)
            const g = Math.round(244 - capped * 162)
            const b = Math.round(236 - capped * 18)
            return [r, g, b, Math.round(state.pointOpacity * 255)]
          }
          const key = state.colorMode === 'annotation' ? point.annotationLabel : point.cluster
          const [r, g, b] = colorForKey(key, state.paletteName)
          return [r, g, b, Math.round(state.pointOpacity * 255)]
        },
        updateTriggers: {
          getPosition: [state.flipHorizontal, state.flipVertical, flipCenter[0], flipCenter[1]],
          getFillColor: [
            mode,
            state.colorMode,
            state.globalHighlight?.sourceClusterId,
            state.paletteName,
            state.pointOpacity,
            state.geneColorGene
          ]
        }
      }),
    [
      displayPoints,
      flipCenter,
      mode,
      state.colorMode,
      state.geneColorGene,
      state.globalHighlight,
      state.paletteName,
      state.pointOpacity,
      state.pointSize
    ]
  )

  const polygonLayer = useMemo(
    () =>
      new PolygonLayer({
        id: `${mode}-saved-polygons`,
        data: displayPolygons as unknown[],
        pickable: false,
        filled: false,
        stroked: true,
        lineWidthUnits: 'pixels',
        lineWidthScale: 1,
        lineWidthMinPixels: 0,
        lineWidthMaxPixels: 16,
        getLineWidth: () => state.polygonStrokeWidth,
        getPolygon: (polygon: any) => polygon.displayVertices,
        getLineColor: (polygon: any) => polygonColor(polygon, state.paletteName)
      }),
    [displayPolygons, mode, state.paletteName, state.polygonStrokeWidth]
  )

  const viewport = useMemo(
    () => {
      const nextViewport = umapView.makeViewport({
        width: frameSize.width,
        height: frameSize.height,
        viewState: {
          target: viewState.target,
          zoom: viewState.zoom
        }
      }) as {
        project: (point: number[]) => number[]
        unproject: (point: number[]) => number[]
      }
      return nextViewport
    },
    [frameSize.height, frameSize.width, viewState.target, viewState.zoom]
  )

  const draftScreenVertices = useMemo(
    () => transformedDraftVertices.map((vertex) => viewport.project(vertex) as number[]),
    [transformedDraftVertices, viewport]
  )

  return (
    <section className="canvas-panel">
      <div className="canvas-toolbar">
        <div className="button-row canvas-buttons">
          <button className="button button-secondary" onClick={() => setViewState(fit)}>
            Reset view
          </button>
          {mode === 'lineage' ? (
            <>
              <button className="button" onClick={state.isDrawing ? state.stopDrawing : state.startDrawing}>
                {state.isDrawing ? 'Stop drawing' : 'Draw polygon'}
              </button>
              <button
                className="button"
                onClick={() => void state.finalizeDraftPolygon()}
                disabled={state.draftVertices.length < 3}
              >
                Close polygon
              </button>
              <button
                className="button button-secondary"
                onClick={state.undoDraftVertex}
                disabled={state.draftVertices.length === 0}
              >
                Undo point
              </button>
              <button className="button button-secondary" onClick={state.clearDraftPolygon}>
                Clear draft
              </button>
              <button className="button button-secondary" onClick={state.clearPolygons}>
                Clear all
              </button>
            </>
          ) : null}
        </div>
        <div className="muted">
          {mode === 'lineage' ? (
            <>
              Displayed points: {visibleBasePoints.length}
              {state.isDrawing ? ` | Draft points: ${state.draftVertices.length}` : ''}
              {state.propagationResult ? ` | Propagated cells: ${state.propagationResult.n_assigned_cells}` : ''}
              {state.colorMode === 'gene' && state.geneColorGene ? ` | Gene: ${state.geneColorGene}` : ''}
            </>
          ) : (
            <>
              Displayed global points: {visibleBasePoints.length}
              {state.globalHighlight
                ? ` | Highlight: ${state.globalHighlight.sourceClusterName} (${state.globalHighlight.highlightedDisplayed}/${state.globalHighlight.highlightedTotal} shown)`
                : ' | Standard cluster colors'}
            </>
          )}
        </div>
      </div>
      <div className="canvas-frame">
        <div ref={frameRef} className="canvas-stage">
          <DeckGL
            layers={mode === 'lineage' ? [pointLayer, polygonLayer] : [pointLayer]}
            views={[umapView]}
            controller={mode === 'lineage' ? !state.isDrawing : true}
            viewState={viewState}
            onViewStateChange={({ viewState: nextViewState }: any) => {
              setViewState({
                target: nextViewState.target,
                zoom: nextViewState.zoom
              })
            }}
            getTooltip={(info: any) => {
              const object = info.object as RenderPoint | undefined
              return object
                ? {
                    text: [
                      `cell_id: ${object.cell_id}`,
                      `cluster: ${object.cluster}`,
                      `annotation: ${object.annotationLabel}`,
                      mode === 'global' && state.globalHighlight
                        ? `highlighted: ${object.is_highlighted ? 'yes' : 'no'}`
                        : '',
                      state.colorMode === 'gene' && state.geneColorGene
                        ? `${state.geneColorGene}: ${(object.gene_expression ?? 0).toFixed(3)}`
                        : '',
                      object.sample_id ? `sample_id: ${object.sample_id}` : '',
                      object.region ? `region: ${object.region}` : ''
                    ]
                      .filter(Boolean)
                      .join('\n')
                  }
                : null
            }}
          />
          {mode === 'lineage' ? (
            <svg
              className={`polygon-overlay ${state.isDrawing ? 'is-active' : ''}`}
              viewBox={`0 0 ${frameSize.width} ${frameSize.height}`}
              preserveAspectRatio="none"
              onClick={(event) => {
                if (!state.isDrawing) {
                  return
                }
                const rect = event.currentTarget.getBoundingClientRect()
                const x = event.clientX - rect.left
                const y = event.clientY - rect.top
                const clickedVertex = viewport.unproject([x, y]) as number[]
                const nextVertex = transformVertex(
                  clickedVertex,
                  flipCenter,
                  state.flipHorizontal,
                  state.flipVertical
                )
                state.addDraftVertex([Number(nextVertex[0]), Number(nextVertex[1])])
              }}
              onDoubleClick={() => {
                if (state.isDrawing && state.draftVertices.length >= 3) {
                  void state.finalizeDraftPolygon()
                }
              }}
            >
              {draftScreenVertices.length > 0 ? (
                <>
                  <polyline
                    points={draftScreenVertices.map((vertex) => `${vertex[0]},${vertex[1]}`).join(' ')}
                    fill="none"
                    stroke="#182126"
                    strokeWidth={String(Math.max(1, state.polygonStrokeWidth))}
                    strokeDasharray="6 4"
                  />
                  {draftScreenVertices.map((vertex, index) => (
                    <circle
                      key={`${vertex[0]}_${vertex[1]}_${index}`}
                      cx={vertex[0]}
                      cy={vertex[1]}
                      r="4"
                      fill="#fffdfa"
                      stroke="#182126"
                      strokeWidth={String(Math.max(1, state.polygonStrokeWidth))}
                    />
                  ))}
                </>
              ) : null}
            </svg>
          ) : null}
        </div>
      </div>
    </section>
  )
}
