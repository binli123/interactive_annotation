import { useEffect, useMemo, useRef, useState } from 'react'
import DeckGL from '@deck.gl/react'
import { OrthographicView } from '@deck.gl/core'
import { PolygonLayer, ScatterplotLayer } from '@deck.gl/layers'
import { useStore } from '../app/store'
import type { PolygonRecord, UmapPoint } from '../app/types'

type ViewMode = 'lineage' | 'global'

type RenderPoint = UmapPoint & {
  annotationLabel: string
  annotationScore?: number
  displayPosition?: [number, number]
}

type RenderPolygon = PolygonRecord & {
  displayVertices: [number, number][]
}

// Tier 1 (≤8 unique values): 8 bold, maximally distinct colors
const TIER1: string[] = [
  '#4e79a7', '#f28e2b', '#e15759', '#76b7b2',
  '#59a14f', '#edc948', '#b07aa1', '#ff9da7',
]

// Tier 2 (9–18 unique values): 18 colors — Tableau 20 first 18
const TIER2: string[] = [
  '#4e79a7', '#a0cbe8', '#f28e2b', '#ffbe7d', '#59a14f', '#8cd17d',
  '#b6992d', '#f1ce63', '#499894', '#86bcb6', '#e15759', '#ff9d9a',
  '#79706e', '#bab0ac', '#d37295', '#fabfd2', '#b07aa1', '#d4a6c8',
]

// Tier 3 (>18 unique values): 40 colors — full-spectrum, capped at 40
const TIER3: string[] = [
  // Reds
  '#e63946', '#c1121f', '#ff4d6d',
  // Oranges
  '#fb8500', '#ffb347', '#f4442e',
  // Yellows
  '#ffd60a', '#f7b731',
  // Yellow-green
  '#80b918', '#c5d86d',
  // Greens
  '#52b788', '#2d6a4f', '#1b4332', '#74c69d',
  // Teals
  '#2ec4b6', '#06d6a0',
  // Cyans
  '#48cae4', '#00b4d8',
  // Blues
  '#4cc9f0', '#4895ef', '#0077b6', '#4361ee', '#023e8a',
  // Indigo/Violet
  '#3a0ca3', '#480ca8', '#7209b7', '#560bad',
  // Purples
  '#8338ec', '#9b5de5', '#b5179e',
  // Pinks
  '#f72585', '#e91e8c', '#ff99c8', '#c77dff',
  // Browns
  '#774936', '#9b7451', '#d4a373',
  // Neutrals
  '#8d99ae', '#495057', '#bcbd22',
]

const umapView = new OrthographicView({ id: 'umap-view' })

function pickPalette(uniqueCount: number): string[] {
  if (uniqueCount <= 8) return TIER1
  if (uniqueCount <= 18) return TIER2
  return TIER3
}

function colorForKey(value: string, palette: string[]): [number, number, number] {
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

function polygonColor(
  polygon: PolygonRecord,
  colorMap: Map<string, [number, number, number]>
): [number, number, number, number] {
  const key = polygon.clusterId || polygon.id
  const [r, g, b] = colorMap.get(key) ?? [128, 128, 128]
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
    draftPolygonId: mode === 'lineage' ? store.draftPolygonId : undefined,
    isDrawing: mode === 'lineage' ? store.isDrawing : false,
    startDrawing: store.startDrawing,
    stopDrawing: store.stopDrawing,
    addDraftVertex: store.addDraftVertex,
    updateDraftVertex: store.updateDraftVertex,
    undoDraftVertex: store.undoDraftVertex,
    finalizeDraftPolygon: store.finalizeDraftPolygon,
    clearDraftPolygon: store.clearDraftPolygon,
    clearPolygons: store.clearPolygons,
    propagationResult: mode === 'lineage' ? store.propagationResult : undefined,
    colorMode: mode === 'lineage' ? store.colorMode : store.globalColorMode,
    clusterVisibility: mode === 'lineage' ? store.clusterVisibility : {},
    clusterLabelEditor: mode === 'lineage' ? store.clusterLabelEditor : undefined,
    geneColorGene: mode === 'lineage' ? store.geneColorGene : store.globalGeneColorGene,
    pointSize: store.pointSize,
    pointOpacity: store.pointOpacity,
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
  const palette = useMemo(() => {
    if (state.colorMode === 'cluster' && state.clusterLabelEditor) {
      return pickPalette(state.clusterLabelEditor.rows.length)
    }
    const colorKey = state.colorMode === 'annotation' ? 'annotationLabel' : 'cluster'
    const unique = new Set(state.points.map((p) => (p as Record<string, unknown>)[colorKey] as string)).size
    return pickPalette(unique)
  }, [state.points, state.colorMode, state.clusterLabelEditor])

  // Sequential assignment from sorted unique IDs — always built from displayed points so
  // it covers every visible cluster even when clusterLabelEditor hasn't loaded yet.
  // Sorting makes the assignment stable and guarantees no two clusters share a slot.
  const clusterColorMap = useMemo((): Map<string, [number, number, number]> => {
    const colorKey = state.colorMode === 'annotation' ? 'annotationLabel' : 'cluster'
    const sortedIds = [...new Set(
      state.points.map((p) => (p as Record<string, unknown>)[colorKey] as string)
    )].sort()
    return new Map(
      sortedIds.map((id, index) => {
        const hex = palette[index % palette.length].replace('#', '')
        return [id, [
          parseInt(hex.slice(0, 2), 16),
          parseInt(hex.slice(2, 4), 16),
          parseInt(hex.slice(4, 6), 16)
        ]] as [string, [number, number, number]]
      })
    )
  }, [state.points, state.colorMode, palette])

  const fit = useMemo(() => fitView(visibleBasePoints), [visibleBasePoints])
  const flipCenter = fit.target
  const [viewState, setViewState] = useState<{ target: number[]; zoom: number }>(fit)
  const [frameSize, setFrameSize] = useState({ width: 1, height: 1 })
  const [draggingVertexIndex, setDraggingVertexIndex] = useState<number | null>(null)

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
      state.polygons
        .filter((polygon) => polygon.id !== state.draftPolygonId)
        .map((polygon) => ({
          ...polygon,
          displayVertices: polygon.vertices.map((vertex) =>
            transformVertex(vertex, flipCenter, state.flipHorizontal, state.flipVertical)
          )
        })),
    [flipCenter, state.draftPolygonId, state.flipHorizontal, state.flipVertical, state.polygons]
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
          if (mode === 'global' && state.globalHighlight && state.colorMode !== 'gene') {
            if (point.is_highlighted) {
              const [r, g, b] = colorForKey(state.globalHighlight.sourceClusterId, palette)
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
          const [r, g, b] = clusterColorMap.get(key) ?? [128, 128, 128]
          return [r, g, b, Math.round(state.pointOpacity * 255)]
        },
        updateTriggers: {
          getPosition: [state.flipHorizontal, state.flipVertical, flipCenter[0], flipCenter[1]],
          getFillColor: [
            mode,
            state.colorMode,
            state.globalHighlight?.sourceClusterId,
            palette,
            clusterColorMap,
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
      palette,
      clusterColorMap,
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
        getLineColor: (polygon: any) => polygonColor(polygon, clusterColorMap)
      }),
    [displayPolygons, mode, palette, clusterColorMap, state.polygonStrokeWidth]
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
                {state.isDrawing ? (state.draftPolygonId ? 'Stop editing' : 'Stop drawing') : 'Draw polygon'}
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
              {state.isDrawing
                ? ` | ${state.draftPolygonId ? 'Editing' : 'Draft'} points: ${state.draftVertices.length}`
                : ''}
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
                if (draggingVertexIndex !== null) {
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
              onPointerMove={(event) => {
                if (draggingVertexIndex === null) {
                  return
                }
                const rect = event.currentTarget.getBoundingClientRect()
                const x = event.clientX - rect.left
                const y = event.clientY - rect.top
                const movedVertex = viewport.unproject([x, y]) as number[]
                const nextVertex = transformVertex(
                  movedVertex,
                  flipCenter,
                  state.flipHorizontal,
                  state.flipVertical
                )
                state.updateDraftVertex(draggingVertexIndex, [Number(nextVertex[0]), Number(nextVertex[1])])
              }}
              onPointerUp={() => setDraggingVertexIndex(null)}
              onPointerLeave={() => setDraggingVertexIndex(null)}
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
                      onPointerDown={(event) => {
                        event.stopPropagation()
                        setDraggingVertexIndex(index)
                      }}
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
