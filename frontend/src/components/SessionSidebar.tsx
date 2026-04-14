import { useMemo } from 'react'
import { useStore } from '../app/store'
import type { PaletteName } from '../app/types'

const paletteOptions: PaletteName[] = ['bright', 'earth', 'pastel']

export default function SessionSidebar() {
  const state = useStore((store) => ({
    activeViewMode: store.activeViewMode,
    setActiveViewMode: store.setActiveViewMode,
    metadata: store.metadata,
    embeddingKey: store.embeddingKey,
    clusterKey: store.clusterKey,
    setEmbeddingKey: store.setEmbeddingKey,
    setClusterKey: store.setClusterKey,
    loadUmap: store.loadUmap,
    refreshPointClusters: store.refreshPointClusters,
    loadClusterLabelEditor: store.loadClusterLabelEditor,
    maxPoints: store.maxPoints,
    minPerCluster: store.minPerCluster,
    maxPerCluster: store.maxPerCluster,
    setMaxPoints: store.setMaxPoints,
    setMinPerCluster: store.setMinPerCluster,
    setMaxPerCluster: store.setMaxPerCluster,
    globalMetadata: store.globalMetadata,
    globalEmbeddingKey: store.globalEmbeddingKey,
    globalClusterKey: store.globalClusterKey,
    setGlobalEmbeddingKey: store.setGlobalEmbeddingKey,
    setGlobalClusterKey: store.setGlobalClusterKey,
    loadGlobalUmap: store.loadGlobalUmap,
    refreshGlobalPointClusters: store.refreshGlobalPointClusters,
    globalMaxPoints: store.globalMaxPoints,
    globalMinPerCluster: store.globalMinPerCluster,
    globalMaxPerCluster: store.globalMaxPerCluster,
    setGlobalMaxPoints: store.setGlobalMaxPoints,
    setGlobalMinPerCluster: store.setGlobalMinPerCluster,
    setGlobalMaxPerCluster: store.setGlobalMaxPerCluster,
    globalHighlight: store.globalHighlight,
    colorMode: store.colorMode,
    globalColorMode: store.globalColorMode,
    geneColorGene: store.geneColorGene,
    globalGeneColorGene: store.globalGeneColorGene,
    setColorMode: store.setColorMode,
    setGlobalColorMode: store.setGlobalColorMode,
    restoreClusterColorView: store.restoreClusterColorView,
    promoteReannotNewToCanonical: store.promoteReannotNewToCanonical,
    pointSize: store.pointSize,
    pointOpacity: store.pointOpacity,
    polygonStrokeWidth: store.polygonStrokeWidth,
    paletteName: store.paletteName,
    setPointSize: store.setPointSize,
    setPointOpacity: store.setPointOpacity,
    setPolygonStrokeWidth: store.setPolygonStrokeWidth,
    setPaletteName: store.setPaletteName,
    flipHorizontal: store.flipHorizontal,
    flipVertical: store.flipVertical,
    setFlipHorizontal: store.setFlipHorizontal,
    setFlipVertical: store.setFlipVertical,
    polygons: store.polygons,
    draftPolygonId: store.draftPolygonId,
    editPolygonVertices: store.editPolygonVertices,
    updatePolygon: store.updatePolygon,
    removePolygon: store.removePolygon,
    propagationMethod: store.propagationMethod,
    propagationScope: store.propagationScope,
    setPropagationMethod: store.setPropagationMethod,
    setPropagationScope: store.setPropagationScope,
    minScore: store.minScore,
    minMargin: store.minMargin,
    annotateAll: store.annotateAll,
    graphSmoothing: store.graphSmoothing,
    setMinScore: store.setMinScore,
    setMinMargin: store.setMinMargin,
    setAnnotateAll: store.setAnnotateAll,
    setGraphSmoothing: store.setGraphSmoothing,
    propagate: store.propagate,
    resetPropagation: store.resetPropagation,
    saveSession: store.saveSession,
    resetSession: store.resetSession,
    sessionSummary: store.sessionSummary,
    propagationResult: store.propagationResult,
    saveResult: store.saveResult,
    clusterLabelEditor: store.clusterLabelEditor,
    referenceClusters: store.referenceClusters,
    sourceClusters: store.sourceClusters,
    referencePropagationName: store.referencePropagationName,
    referencePropagationNeighbors: store.referencePropagationNeighbors,
    referencePropagationResult: store.referencePropagationResult,
    toggleReferenceCluster: store.toggleReferenceCluster,
    toggleSourceCluster: store.toggleSourceCluster,
    setReferencePropagationName: store.setReferencePropagationName,
    setReferencePropagationNeighbors: store.setReferencePropagationNeighbors,
    runReferencePropagation: store.runReferencePropagation,
    busy: store.busy
  }))

  const resolutionKeys = useMemo(
    () => state.metadata?.summary_resolution_trials.map((row) => String(row.cluster_key ?? '')) ?? [],
    [state.metadata]
  )
  const canPromoteReannotNew = (state.metadata?.cluster_keys ?? []).includes('reannot_label_new')

  return (
    <div className="sidebar-stack">
      <section className="panel">
        <h2>View</h2>
        <div className="tab-strip">
          <button
            className={`tab-button ${state.activeViewMode === 'lineage' ? 'is-active' : ''}`}
            onClick={() => state.setActiveViewMode('lineage')}
          >
            Lineage
          </button>
          <button
            className={`tab-button ${state.activeViewMode === 'global' ? 'is-active' : ''}`}
            onClick={() => state.setActiveViewMode('global')}
          >
            Global
          </button>
        </div>
        {state.activeViewMode === 'lineage' ? (
          <>
            <label className="field">
              <span>Embedding</span>
              <select
                value={state.embeddingKey}
                onChange={(event) => {
                  const value = event.target.value
                  state.setEmbeddingKey(value)
                  void state.loadUmap({ embeddingKey: value })
                }}
                disabled={!state.metadata}
              >
                {(state.metadata?.embedding_keys ?? []).map((key) => (
                  <option key={key} value={key}>
                    {key}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>Cluster key</span>
              <select
                value={state.clusterKey}
                onChange={(event) => {
                  const value = event.target.value
                  state.setClusterKey(value)
                  void state.refreshPointClusters(value)
                  void state.loadClusterLabelEditor()
                }}
                disabled={!state.metadata}
              >
                {(state.metadata?.cluster_keys ?? []).map((key) => (
                  <option key={key} value={key}>
                    {key}
                  </option>
                ))}
              </select>
            </label>
            <div className="sampling-grid">
              <label className="field sampling-wide">
                <span>Overall max points</span>
                <input
                  type="number"
                  value={state.maxPoints}
                  onChange={(event) => state.setMaxPoints(Number(event.target.value))}
                />
              </label>
              <label className="field">
                <span>Min/cluster</span>
                <input
                  type="number"
                  min="0"
                  value={state.minPerCluster}
                  onChange={(event) => state.setMinPerCluster(Number(event.target.value))}
                />
              </label>
              <label className="field">
                <span>Cluster-wise cap</span>
                <input
                  type="number"
                  min="0"
                  value={state.maxPerCluster}
                  onChange={(event) => state.setMaxPerCluster(Number(event.target.value))}
                />
              </label>
            </div>
            <div className="button-row">
              <button className="button" onClick={() => void state.loadUmap()} disabled={state.busy}>
                Reload UMAP
              </button>
              <select
                value={state.colorMode}
                onChange={(event) =>
                  state.setColorMode(event.target.value as 'cluster' | 'annotation' | 'gene')
                }
              >
                <option value="cluster">Color by cluster</option>
                <option value="annotation">Color by annotation</option>
                {state.geneColorGene ? (
                  <option value="gene">Color by gene: {state.geneColorGene}</option>
                ) : null}
              </select>
            </div>
            <button
              className="button button-secondary"
              onClick={state.restoreClusterColorView}
              disabled={state.colorMode === 'cluster'}
            >
              Restore cluster colors
            </button>
            <button
              className="button button-secondary"
              onClick={() => void state.promoteReannotNewToCanonical()}
              disabled={!canPromoteReannotNew || state.busy}
            >
              Use reannot_label_new as canonical
            </button>
            {resolutionKeys.length > 0 ? (
              <p className="muted">Available resolutions: {resolutionKeys.join(', ')}</p>
            ) : null}
            {!canPromoteReannotNew && state.metadata ? (
              <p className="muted">`reannot_label_new` is not available on this object.</p>
            ) : null}
          </>
        ) : (
          <>
            <label className="field">
              <span>Embedding</span>
              <select
                value={state.globalEmbeddingKey}
                onChange={(event) => {
                  const value = event.target.value
                  state.setGlobalEmbeddingKey(value)
                  void state.loadGlobalUmap({ embeddingKey: value })
                }}
                disabled={!state.globalMetadata}
              >
                {(state.globalMetadata?.embedding_keys ?? []).map((key) => (
                  <option key={key} value={key}>
                    {key}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>Cluster key</span>
              <select
                value={state.globalClusterKey}
                onChange={(event) => {
                  const value = event.target.value
                  state.setGlobalClusterKey(value)
                  void state.refreshGlobalPointClusters(value)
                }}
                disabled={!state.globalMetadata}
              >
                {(state.globalMetadata?.cluster_keys ?? []).map((key) => (
                  <option key={key} value={key}>
                    {key}
                  </option>
                ))}
              </select>
            </label>
            <div className="sampling-grid">
              <label className="field sampling-wide">
                <span>Overall max points</span>
                <input
                  type="number"
                  value={state.globalMaxPoints}
                  onChange={(event) => state.setGlobalMaxPoints(Number(event.target.value))}
                />
              </label>
              <label className="field">
                <span>Min/cluster</span>
                <input
                  type="number"
                  min="0"
                  value={state.globalMinPerCluster}
                  onChange={(event) => state.setGlobalMinPerCluster(Number(event.target.value))}
                />
              </label>
              <label className="field">
                <span>Cluster-wise cap</span>
                <input
                  type="number"
                  min="0"
                  value={state.globalMaxPerCluster}
                  onChange={(event) => state.setGlobalMaxPerCluster(Number(event.target.value))}
                />
              </label>
            </div>
            <div className="button-row">
              <button className="button" onClick={() => void state.loadGlobalUmap()} disabled={state.busy}>
                Reload Global UMAP
              </button>
              <select
                value={state.globalColorMode}
                onChange={(event) => state.setGlobalColorMode(event.target.value as 'cluster' | 'gene')}
              >
                <option value="cluster">Color by cluster</option>
                {state.globalGeneColorGene ? (
                  <option value="gene">Color by gene: {state.globalGeneColorGene}</option>
                ) : null}
              </select>
            </div>
            <button
              className="button button-secondary"
              onClick={state.restoreClusterColorView}
              disabled={state.globalColorMode === 'cluster' && !state.globalHighlight}
            >
              Restore cluster colors
            </button>
            {state.globalHighlight ? (
              <p className="muted">
                Highlighting {state.globalHighlight.sourceClusterName} with{' '}
                {state.globalHighlight.highlightedDisplayed.toLocaleString()} visible matches.
              </p>
            ) : (
              <p className="muted">Standard global cluster colors are active.</p>
            )}
          </>
        )}
      </section>

      <section className="panel">
        <h2>Visualization</h2>
        <label className="field">
          <span>Dot size</span>
          <input
            type="range"
            min="0.5"
            max="16"
            step="0.1"
            value={state.pointSize}
            onChange={(event) => state.setPointSize(Number(event.target.value))}
          />
        </label>
        <label className="field">
          <span>Transparency</span>
          <input
            type="range"
            min="0.02"
            max="1"
            step="0.02"
            value={state.pointOpacity}
            onChange={(event) => state.setPointOpacity(Number(event.target.value))}
          />
        </label>
        <label className="field">
          <span>Polygon boundary</span>
          <input
            type="range"
            min="0.5"
            max="8"
            step="0.1"
            value={state.polygonStrokeWidth}
            onChange={(event) => state.setPolygonStrokeWidth(Number(event.target.value))}
          />
        </label>
        <label className="field">
          <span>Palette</span>
          <select
            value={state.paletteName}
            onChange={(event) => state.setPaletteName(event.target.value as PaletteName)}
          >
            {paletteOptions.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
        <label className="checkbox-row">
          <input
            type="checkbox"
            checked={state.flipHorizontal}
            onChange={(event) => state.setFlipHorizontal(event.target.checked)}
          />
          <span>Flip horizontally</span>
        </label>
        <label className="checkbox-row">
          <input
            type="checkbox"
            checked={state.flipVertical}
            onChange={(event) => state.setFlipVertical(event.target.checked)}
          />
          <span>Flip vertically</span>
        </label>
      </section>

      <section className="panel">
        <h2>Polygons</h2>
        {state.polygons.length === 0 ? (
          <p className="muted">Draw a polygon on the UMAP, then edit its cluster ID and cluster name here.</p>
        ) : (
          <div className="polygon-list">
            {state.polygons.map((polygon) => (
              <div className="polygon-card" key={polygon.id}>
                <label className="checkbox-row">
                  <input
                    type="checkbox"
                    checked={polygon.includeForPropagation}
                    onChange={(event) =>
                      state.updatePolygon(polygon.id, { includeForPropagation: event.target.checked })
                    }
                  />
                  <span>Include in propagate</span>
                </label>
                <label className="field">
                  <span>Cluster ID</span>
                  <input
                    value={polygon.clusterId}
                    onChange={(event) => state.updatePolygon(polygon.id, { clusterId: event.target.value })}
                    placeholder="e.g. Treg"
                  />
                </label>
                <label className="field">
                  <span>Cluster name</span>
                  <input
                    value={polygon.clusterName}
                    onChange={(event) => state.updatePolygon(polygon.id, { clusterName: event.target.value })}
                    placeholder="Human-readable name"
                  />
                </label>
                <div className="polygon-meta">
                  <div>Polygon: {polygon.id}</div>
                  <div>Cells inside: {polygon.nCells}</div>
                  <div>
                    Leiden mix:{' '}
                    {polygon.clusterSummary.slice(0, 3).map((row) => `${row.cluster}=${row.n_cells}`).join(', ') ||
                      'NA'}
                  </div>
                </div>
                <button
                  className="button button-secondary"
                  onClick={() => state.editPolygonVertices(polygon.id)}
                  disabled={state.busy}
                >
                  {state.draftPolygonId === polygon.id ? 'Editing vertices' : 'Edit vertices'}
                </button>
                <button
                  className="button button-secondary"
                  onClick={() => state.removePolygon(polygon.id)}
                  disabled={state.busy}
                >
                  Remove polygon
                </button>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="panel">
        <h2>Propagate</h2>
        <label className="field">
          <span>Method</span>
          <select
            value={state.propagationMethod}
            onChange={(event) =>
              state.setPropagationMethod(event.target.value as 'graph_diffusion' | 'knn_vote')
            }
          >
            <option value="graph_diffusion">Graph diffusion</option>
            <option value="knn_vote">kNN vote</option>
          </select>
        </label>
        <label className="field">
          <span>Scope</span>
          <select
            value={state.propagationScope}
            onChange={(event) =>
              state.setPropagationScope(
                event.target.value as
                  | 'polygon_only'
                  | 'selected_clusters_only'
                  | 'same_connected_neighborhood'
                  | 'whole_lineage'
              )
            }
          >
            <option value="polygon_only">Polygon only</option>
            <option value="selected_clusters_only">Selected clusters only</option>
            <option value="same_connected_neighborhood">Same connected neighborhood</option>
            <option value="whole_lineage">Whole lineage</option>
          </select>
        </label>
        <div className="two-col">
          <label className="field">
            <span>Min score</span>
            <input
              type="number"
              step="0.05"
              min="0"
              max="1"
              value={state.minScore}
              onChange={(event) => state.setMinScore(Number(event.target.value))}
              disabled={state.annotateAll}
            />
          </label>
          <label className="field">
            <span>Min margin</span>
            <input
              type="number"
              step="0.05"
              min="0"
              max="1"
              value={state.minMargin}
              onChange={(event) => state.setMinMargin(Number(event.target.value))}
              disabled={state.annotateAll}
            />
          </label>
        </div>
        <label className="checkbox-row">
          <input
            type="checkbox"
            checked={state.annotateAll}
            onChange={(event) => state.setAnnotateAll(event.target.checked)}
          />
          <span>Annotate all</span>
        </label>
        {state.propagationMethod === 'graph_diffusion' ? (
          <label className="field">
            <span>Graph smoothing</span>
            <input
              type="range"
              min="0"
              max="1"
              step="0.05"
              value={state.graphSmoothing}
              onChange={(event) => state.setGraphSmoothing(Number(event.target.value))}
            />
          </label>
        ) : null}
        {state.propagationMethod === 'graph_diffusion' ? (
          <p className="muted">
            Graph smoothing: {state.graphSmoothing.toFixed(2)}
            {state.annotateAll ? ' | score and margin are ignored' : ''}
          </p>
        ) : state.annotateAll ? (
          <p className="muted">Annotate all ignores score and margin thresholds.</p>
        ) : null}
        <button className="button" onClick={() => void state.propagate()} disabled={state.busy}>
          Propagate selected polygons
        </button>
        <button className="button button-secondary" onClick={() => void state.resetPropagation()} disabled={state.busy}>
          Reset propagation
        </button>
      </section>

      <section className="panel">
        <h2>Propagate (Reference-Based)</h2>
        <label className="field">
          <span>Output name</span>
          <input
            value={state.referencePropagationName}
            onChange={(event) => state.setReferencePropagationName(event.target.value)}
            placeholder="new"
          />
        </label>
        <label className="field">
          <span>kNN neighbors</span>
          <input
            type="number"
            min="1"
            max="100"
            value={state.referencePropagationNeighbors}
            onChange={(event) => state.setReferencePropagationNeighbors(Number(event.target.value))}
          />
        </label>
        {!state.clusterLabelEditor ? (
          <p className="muted">Load a cluster key to choose reference and source clusters.</p>
        ) : (
          <div className="reference-propagation-grid">
            <div className="cluster-label-grid-head">Reference</div>
            <div className="cluster-label-grid-head">Source</div>
            <div className="cluster-label-grid-head">Cluster ID</div>
            <div className="cluster-label-grid-head">Cells</div>
            {state.clusterLabelEditor.rows.map((row) => (
              <div className="reference-propagation-row" key={row.cluster_id}>
                <label className="cluster-visibility-cell">
                  <input
                    type="checkbox"
                    checked={state.referenceClusters.includes(row.cluster_id)}
                    onChange={() => state.toggleReferenceCluster(row.cluster_id)}
                  />
                </label>
                <label className="cluster-visibility-cell">
                  <input
                    type="checkbox"
                    checked={state.sourceClusters.includes(row.cluster_id)}
                    onChange={() => state.toggleSourceCluster(row.cluster_id)}
                  />
                </label>
                <div className="mono">{row.cluster_id}</div>
                <div>{row.n_cells.toLocaleString()}</div>
              </div>
            ))}
          </div>
        )}
        <button className="button" onClick={() => void state.runReferencePropagation()} disabled={state.busy}>
          Apply kNN vote to source clusters
        </button>
        {state.referencePropagationResult ? (
          <p className="muted">
            Wrote <span className="mono">{state.referencePropagationResult.new_cluster_key}</span> with{' '}
            {state.referencePropagationResult.n_source_cells.toLocaleString()} source cells reassigned.
          </p>
        ) : null}
      </section>

      <section className="panel">
        <h2>Session</h2>
        <button className="button" onClick={() => void state.saveSession()} disabled={state.busy}>
          Save reannotated object
        </button>
        <button className="button button-secondary" onClick={() => void state.resetSession()} disabled={state.busy}>
          Reset session
        </button>
        {state.sessionSummary ? (
          <div className="summary-block">
            <div>Seed cells: {state.sessionSummary.n_seed_cells}</div>
            <div>Polygons: {state.sessionSummary.n_polygons}</div>
            <div>Labels: {Object.entries(state.sessionSummary.labels).map(([k, v]) => `${k}=${v}`).join(', ')}</div>
          </div>
        ) : (
          <p className="muted">No propagated session yet.</p>
        )}
        {state.propagationResult ? (
          <div className="summary-block">
            <div>Assigned: {state.propagationResult.n_assigned_cells}</div>
            <div>Eligible: {state.propagationResult.n_eligible_cells}</div>
            <div>
              Labels:{' '}
              {Object.entries(state.propagationResult.label_counts)
                .map(([label, count]) => `${label}=${count}`)
                .join(', ')}
            </div>
          </div>
        ) : null}
        {state.saveResult ? (
          <div className="summary-block">
            <div className="mono small">{state.saveResult.object_path}</div>
          </div>
        ) : null}
      </section>
    </div>
  )
}
