import { useStore } from '../app/store'

export default function DEPanel() {
  const state = useStore((store) => ({
    clusterLabelEditor: store.clusterLabelEditor,
    clusterVisibility: store.clusterVisibility,
    clusterKey: store.clusterKey,
    deTargetClusters: store.deTargetClusters,
    deReferenceClusters: store.deReferenceClusters,
    deResult: store.deResult,
    toggleDeTargetCluster: store.toggleDeTargetCluster,
    toggleDeReferenceCluster: store.toggleDeReferenceCluster,
    runDifferentialExpression: store.runDifferentialExpression,
    addSelectedGenes: store.addSelectedGenes,
    busy: store.busy
  }))

  const visibleRows = (state.clusterLabelEditor?.rows ?? []).filter(
    (row) => state.clusterVisibility[row.cluster_id] ?? true
  )

  return (
    <section className="panel">
      <h2>Differential Expression</h2>
      <p className="muted">Compare gene expression between cluster groups.</p>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem', marginBottom: '0.5rem' }}>
        <div>
          <h3>Target clusters</h3>
          <p className="muted" style={{ fontSize: '0.75rem' }}>Cells to test</p>
          <div className="cluster-list" style={{ maxHeight: 150, overflowY: 'auto' }}>
            {visibleRows.map((row) => (
              <label key={row.cluster_id} className="gene-row">
                <input
                  type="checkbox"
                  checked={state.deTargetClusters.includes(row.cluster_id)}
                  onChange={() => state.toggleDeTargetCluster(row.cluster_id)}
                />
                <span className="mono gene-name">{row.display_name ?? row.cluster_id}</span>
                <span className="small">{row.n_cells.toLocaleString()}</span>
              </label>
            ))}
          </div>
        </div>
        <div>
          <h3>Reference clusters</h3>
          <p className="muted" style={{ fontSize: '0.75rem' }}>Leave empty = all others</p>
          <div className="cluster-list" style={{ maxHeight: 150, overflowY: 'auto' }}>
            {visibleRows.map((row) => (
              <label key={row.cluster_id} className="gene-row">
                <input
                  type="checkbox"
                  checked={state.deReferenceClusters.includes(row.cluster_id)}
                  onChange={() => state.toggleDeReferenceCluster(row.cluster_id)}
                />
                <span className="mono gene-name">{row.display_name ?? row.cluster_id}</span>
                <span className="small">{row.n_cells.toLocaleString()}</span>
              </label>
            ))}
          </div>
        </div>
      </div>

      <button
        className="button"
        disabled={state.busy || state.deTargetClusters.length === 0}
        onClick={() => void state.runDifferentialExpression()}
      >
        Run DE Analysis
      </button>

      {state.deResult && (
        <div style={{ marginTop: '0.75rem' }}>
          <div className="cluster-label-header">
            <div>
              <h3>Results</h3>
              <p className="muted">
                {state.deResult.n_target_cells.toLocaleString()} target vs{' '}
                {state.deResult.n_reference_cells.toLocaleString()} reference cells · {state.deResult.method}
              </p>
            </div>
            <button
              className="button button-secondary"
              onClick={() => state.addSelectedGenes(state.deResult!.genes.slice(0, 20).map((g) => g.gene_name))}
            >
              Add top 20 to Gene Panel
            </button>
          </div>
          <div style={{ overflowX: 'auto', marginTop: '0.5rem' }}>
            <table style={{ width: '100%', fontSize: '0.75rem', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border)' }}>
                  <th style={{ textAlign: 'left', padding: '2px 4px' }}>Gene</th>
                  <th style={{ textAlign: 'right', padding: '2px 4px' }}>log₂FC</th>
                  <th style={{ textAlign: 'right', padding: '2px 4px' }}>adj. p</th>
                  <th style={{ textAlign: 'right', padding: '2px 4px' }}>mean target</th>
                  <th style={{ textAlign: 'right', padding: '2px 4px' }}>mean ref</th>
                </tr>
              </thead>
              <tbody>
                {state.deResult.genes.slice(0, 50).map((gene) => (
                  <tr
                    key={gene.gene_name}
                    style={{ borderBottom: '1px solid var(--border-subtle, #eee)' }}
                  >
                    <td className="mono" style={{ padding: '2px 4px' }}>{gene.gene_name}</td>
                    <td
                      style={{
                        textAlign: 'right',
                        padding: '2px 4px',
                        color: gene.log_fold_change > 0 ? '#2e7d32' : '#c62828'
                      }}
                    >
                      {gene.log_fold_change.toFixed(2)}
                    </td>
                    <td style={{ textAlign: 'right', padding: '2px 4px' }}>
                      {gene.p_val_adj < 0.001 ? gene.p_val_adj.toExponential(1) : gene.p_val_adj.toFixed(3)}
                    </td>
                    <td style={{ textAlign: 'right', padding: '2px 4px' }}>{gene.mean_target.toFixed(3)}</td>
                    <td style={{ textAlign: 'right', padding: '2px 4px' }}>{gene.mean_reference.toFixed(3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  )
}
