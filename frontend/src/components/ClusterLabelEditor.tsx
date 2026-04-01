import { useStore } from '../app/store'

export default function ClusterLabelEditor() {
  const state = useStore((store) => ({
    clusterKey: store.clusterKey,
    clusterLabelEditor: store.clusterLabelEditor,
    clusterLabelSaveResult: store.clusterLabelSaveResult,
    clusterVisibility: store.clusterVisibility,
    setClusterVisibility: store.setClusterVisibility,
    updateClusterLabelName: store.updateClusterLabelName,
    saveClusterLabelEditor: store.saveClusterLabelEditor,
    busy: store.busy
  }))

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
        <button className="button" onClick={() => void state.saveClusterLabelEditor()} disabled={state.busy}>
          Save names to object
        </button>
      </div>
      <div className="cluster-label-grid">
        <div className="cluster-label-grid-head">Show</div>
        <div className="cluster-label-grid-head">Cluster ID</div>
        <div className="cluster-label-grid-head">Cells</div>
        <div className="cluster-label-grid-head">Human-readable name</div>
        {state.clusterLabelEditor.rows.map((row) => (
          <div className="cluster-label-row" key={row.cluster_id}>
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
          </div>
        ))}
      </div>
      {state.clusterLabelSaveResult ? (
        <p className="muted">
          Saved {state.clusterLabelSaveResult.n_updated} cluster names to{' '}
          <span className="mono">{state.clusterLabelSaveResult.display_column}</span>.
        </p>
      ) : null}
    </section>
  )
}
