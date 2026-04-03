import { useEffect, useMemo, useState } from 'react'
import { useStore } from '../app/store'

export default function ClusterLabelEditor() {
  const [moveClusterId, setMoveClusterId] = useState<string | null>(null)
  const [destinationObjectId, setDestinationObjectId] = useState('')
  const state = useStore((store) => ({
    objects: store.objects,
    selectedObjectId: store.selectedObjectId,
    clusterKey: store.clusterKey,
    clusterLabelEditor: store.clusterLabelEditor,
    clusterLabelSaveResult: store.clusterLabelSaveResult,
    moveClusterPreview: store.moveClusterPreview,
    moveClusterResult: store.moveClusterResult,
    moveClusterUndoStatus: store.moveClusterUndoStatus,
    moveClusterUndoResult: store.moveClusterUndoResult,
    globalMetadata: store.globalMetadata,
    clusterVisibility: store.clusterVisibility,
    setClusterVisibility: store.setClusterVisibility,
    updateClusterLabelName: store.updateClusterLabelName,
    saveClusterLabelEditor: store.saveClusterLabelEditor,
    highlightClusterInGlobal: store.highlightClusterInGlobal,
    restoreGlobalClusterColors: store.restoreGlobalClusterColors,
    globalHighlight: store.globalHighlight,
    previewMoveCluster: store.previewMoveCluster,
    clearMoveClusterPreview: store.clearMoveClusterPreview,
    moveClusterToObject: store.moveClusterToObject,
    undoLatestMoveCluster: store.undoLatestMoveCluster,
    busy: store.busy
  }))

  const destinationObjects = useMemo(
    () => state.objects.filter((object) => object.object_id !== state.selectedObjectId && object.is_valid),
    [state.objects, state.selectedObjectId]
  )

  useEffect(() => {
    if (!moveClusterId || !destinationObjectId) {
      state.clearMoveClusterPreview()
      return
    }
    void state.previewMoveCluster(moveClusterId, destinationObjectId)
  }, [destinationObjectId, moveClusterId, state.clearMoveClusterPreview, state.previewMoveCluster])

  if (!state.clusterKey || !state.clusterLabelEditor) {
    return null
  }

  return (
    <section className="panel cluster-label-editor">
      <div className="cluster-label-header">
        <div>
          <h2>Cluster Names</h2>
          <p className="muted">
            Current key: <span className="mono">{state.clusterLabelEditor.cluster_key}</span>
            {' | '}
            Save column: <span className="mono">{state.clusterLabelEditor.display_column}</span>
          </p>
        </div>
        <div className="cluster-label-actions">
          <button className="button" onClick={() => void state.saveClusterLabelEditor()} disabled={state.busy}>
            Save names to object
          </button>
          <button
            className="button button-secondary"
            onClick={() => void state.restoreGlobalClusterColors()}
            disabled={!state.globalHighlight || state.busy}
          >
            Restore cluster colors
          </button>
          <button
            className="button button-secondary"
            onClick={() => void state.undoLatestMoveCluster()}
            disabled={!state.moveClusterUndoStatus?.available || state.busy}
          >
            Undo Moving cluster
          </button>
        </div>
      </div>
      <div className="cluster-label-grid cluster-label-grid-actions">
        <div className="cluster-label-grid-head">Show</div>
        <div className="cluster-label-grid-head">Cluster ID</div>
        <div className="cluster-label-grid-head">Cells</div>
        <div className="cluster-label-grid-head">Human-readable name</div>
        <div className="cluster-label-grid-head">Global</div>
        <div className="cluster-label-grid-head">Move</div>
        {state.clusterLabelEditor.rows.map((row) => (
          <div className="cluster-label-row cluster-label-row-actions" key={row.cluster_id}>
            <label className="cluster-visibility-cell">
              <input
                type="checkbox"
                checked={state.clusterVisibility[row.cluster_id] ?? true}
                onChange={(event) => state.setClusterVisibility(row.cluster_id, event.target.checked)}
              />
            </label>
            <div className="mono">{row.cluster_id}</div>
            <div>{row.n_cells.toLocaleString()}</div>
            <input
              value={row.display_name ?? ''}
              onChange={(event) => state.updateClusterLabelName(row.cluster_id, event.target.value)}
              placeholder={`Name for ${row.cluster_id}`}
            />
              <button
                className="button button-secondary button-inline"
                onClick={() => void state.highlightClusterInGlobal(row.cluster_id, row.display_name ?? row.cluster_id)}
                disabled={state.busy || !state.globalMetadata}
              >
                Highlight
              </button>
            <button
              className="button button-secondary button-inline"
              onClick={() => {
                state.clearMoveClusterPreview()
                setMoveClusterId(row.cluster_id)
                setDestinationObjectId(destinationObjects[0]?.object_id ?? '')
              }}
              disabled={state.busy || destinationObjects.length === 0}
            >
              Move to
            </button>
          </div>
        ))}
      </div>
      {state.clusterLabelSaveResult ? (
        <p className="muted">
          Saved {state.clusterLabelSaveResult.n_updated} cluster names to{' '}
          <span className="mono">{state.clusterLabelSaveResult.display_column}</span>.
        </p>
      ) : null}
      {state.moveClusterResult ? (
        <p className="muted">
          Moved {state.moveClusterResult.n_moved_cells.toLocaleString()} cells from{' '}
          <span className="mono">{state.moveClusterResult.cluster_id}</span> into{' '}
          <span className="mono">{state.moveClusterResult.destination_object_path}</span>
          {state.moveClusterResult.n_overwritten_cells > 0
            ? ` with ${state.moveClusterResult.n_overwritten_cells.toLocaleString()} overwritten destination cell IDs.`
            : '.'}
        </p>
      ) : null}
      {state.moveClusterUndoResult ? (
        <p className="muted">
          Undid the latest move of {state.moveClusterUndoResult.n_moved_cells.toLocaleString()} cells for{' '}
          <span className="mono">{state.moveClusterUndoResult.display_name}</span>.
        </p>
      ) : null}
      {state.moveClusterUndoStatus?.available ? (
        <p className="muted">
          Latest move available to undo: {state.moveClusterUndoStatus.n_moved_cells?.toLocaleString() ?? 0} cells into{' '}
          <span className="mono">{state.moveClusterUndoStatus.destination_object_path}</span>.
        </p>
      ) : null}
      {moveClusterId ? (
        <div className="modal-backdrop" role="presentation">
          <div className="modal-card" role="dialog" aria-modal="true" aria-labelledby="move-cluster-title">
            <h3 id="move-cluster-title">Move cluster</h3>
            <p className="muted">
              Move <span className="mono">{moveClusterId}</span> into another lineage object.
            </p>
            <label className="field">
              <span>Destination object</span>
              <select
                value={destinationObjectId}
                onChange={(event) => setDestinationObjectId(event.target.value)}
              >
                {destinationObjects.map((object) => (
                  <option key={object.object_id} value={object.object_id}>
                    {object.lineage_name} | {object.object_path}
                  </option>
                ))}
              </select>
            </label>
            <div className="modal-actions">
              {state.moveClusterPreview ? (
                <div className="summary-block">
                  <div>Cells to move: {state.moveClusterPreview.n_moved_cells.toLocaleString()}</div>
                  <div>Destination cell IDs overwritten: {state.moveClusterPreview.n_overwritten_cells.toLocaleString()}</div>
                  <div>
                    Assigned destination cluster ID:{' '}
                    <span className="mono">{state.moveClusterPreview.assigned_cluster_id}</span>
                  </div>
                  <div>
                    Destination label:{' '}
                    <span className="mono">{state.moveClusterPreview.display_name}</span>
                  </div>
                </div>
              ) : null}
            </div>
            <div className="modal-actions">
              <button
                className="button"
                disabled={!destinationObjectId || state.busy || !state.moveClusterPreview}
                onClick={async () => {
                  await state.moveClusterToObject(moveClusterId, destinationObjectId)
                  setMoveClusterId(null)
                  setDestinationObjectId('')
                }}
              >
                OK
              </button>
              <button
                className="button button-secondary"
                onClick={() => {
                  setMoveClusterId(null)
                  setDestinationObjectId('')
                  state.clearMoveClusterPreview()
                }}
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  )
}
