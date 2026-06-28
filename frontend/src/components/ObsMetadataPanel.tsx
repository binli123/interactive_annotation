import { useEffect } from 'react'
import { useStore } from '../app/store'

// Select stable primitives + action refs separately to avoid spurious re-renders
const loadObsColumnsSelector = (store: ReturnType<typeof useStore.getState>) => store.loadObsColumns
const setActiveObsColumnSelector = (store: ReturnType<typeof useStore.getState>) => store.setActiveObsColumn

export default function ObsMetadataPanel() {
  const loadObsColumns = useStore(loadObsColumnsSelector)
  const setActiveObsColumn = useStore(setActiveObsColumnSelector)
  const state = useStore((store) => ({
    obsColumns: store.obsColumns,
    activeObsColumn: store.activeObsColumn,
    obsColorValues: store.obsColorValues,
    selectedObjectId: store.selectedObjectId,
    activeViewMode: store.activeViewMode,
    metadata: store.metadata,
    busy: store.busy
  }))

  useEffect(() => {
    void loadObsColumns()
  }, [state.selectedObjectId, state.activeViewMode, loadObsColumns])

  const qcColumns = (state.obsColumns ?? []).filter((c) => c.is_qc)
  const numericColumns = (state.obsColumns ?? []).filter((c) => c.is_numeric && !c.is_qc)
  const categoricalColumns = (state.obsColumns ?? []).filter((c) => !c.is_numeric)

  const activeCol = state.obsColumns?.find((c) => c.name === state.activeObsColumn)

  return (
    <section className="panel">
      <h2>Obs Metadata Coloring</h2>
      <p className="muted">Color the UMAP by any observation column (batch, QC, metadata).</p>

      {qcColumns.length > 0 && (
        <>
          <h3>QC Metrics</h3>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.25rem', marginBottom: '0.5rem' }}>
            {qcColumns.map((col) => (
              <button
                key={col.name}
                className={`button button-secondary ${state.activeObsColumn === col.name ? 'is-active' : ''}`}
                style={{ fontSize: '0.75rem', padding: '2px 8px' }}
                onClick={() => void setActiveObsColumn(state.activeObsColumn === col.name ? undefined : col.name)}
              >
                {col.name}
              </button>
            ))}
          </div>
        </>
      )}

      <label className="field">
        <span>Numeric columns</span>
        <select
          value={activeCol?.is_numeric && !activeCol?.is_qc ? state.activeObsColumn ?? '' : ''}
          onChange={(e) => void setActiveObsColumn(e.target.value || undefined)}
        >
          <option value="">— select —</option>
          {numericColumns.map((col) => (
            <option key={col.name} value={col.name}>{col.name}</option>
          ))}
        </select>
      </label>

      <label className="field">
        <span>Categorical columns</span>
        <select
          value={activeCol && !activeCol.is_numeric ? state.activeObsColumn ?? '' : ''}
          onChange={(e) => void setActiveObsColumn(e.target.value || undefined)}
        >
          <option value="">— select —</option>
          {categoricalColumns.map((col) => (
            <option key={col.name} value={col.name}>
              {col.name}{col.n_unique != null ? ` (${col.n_unique} values)` : ''}
            </option>
          ))}
        </select>
      </label>

      {state.activeObsColumn && (
        <div style={{ marginTop: '0.5rem' }}>
          <p className="muted">
            Active: <strong>{state.activeObsColumn}</strong> · {activeCol?.dtype ?? ''} ·{' '}
            {Object.keys(state.obsColorValues).length.toLocaleString()} values loaded
          </p>
          <button
            className="button button-secondary"
            onClick={() => void setActiveObsColumn(undefined)}
          >
            Clear obs coloring
          </button>
        </div>
      )}

      {!state.obsColumns && (
        <p className="muted">Load an object to see available columns.</p>
      )}
    </section>
  )
}
