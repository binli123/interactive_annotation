import { useState } from 'react'
import { useStore } from '../app/store'

export default function AnnotationDiffPanel() {
  const state = useStore((store) => ({
    metadata: store.metadata,
    clusterKey: store.clusterKey,
    annotationDiffResult: store.annotationDiffResult,
    runAnnotationDiff: store.runAnnotationDiff,
    busy: store.busy
  }))

  const clusterKeys = state.metadata?.cluster_keys ?? []
  const [keyA, setKeyA] = useState<string>('')
  const [keyB, setKeyB] = useState<string>('')

  const effectiveKeyA = keyA || clusterKeys[0] || ''
  const effectiveKeyB = keyB || clusterKeys[1] || ''

  const result = state.annotationDiffResult
  const canCompare = Boolean(effectiveKeyA) && Boolean(effectiveKeyB) && effectiveKeyA !== effectiveKeyB

  const changedTransitions = result?.transitions.filter((t) => t.label_a !== t.label_b) ?? []

  if (clusterKeys.length < 2) {
    return (
      <section className="panel">
        <h2>Annotation Diff</h2>
        <p className="muted">At least two cluster columns are required. Save annotations to create a second column.</p>
      </section>
    )
  }

  return (
    <section className="panel">
      <h2>Annotation Diff</h2>
      <p className="muted">Compare two cluster columns cell-by-cell to see what changed.</p>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem', marginBottom: '0.5rem' }}>
        <label className="field">
          <span>Column A (before)</span>
          <select value={effectiveKeyA} onChange={(e) => setKeyA(e.target.value)}>
            {clusterKeys.map((key) => <option key={key} value={key}>{key}</option>)}
          </select>
        </label>
        <label className="field">
          <span>Column B (after)</span>
          <select value={effectiveKeyB} onChange={(e) => setKeyB(e.target.value)}>
            {clusterKeys.map((key) => <option key={key} value={key}>{key}</option>)}
          </select>
        </label>
      </div>

      <button
        className="button"
        disabled={state.busy || !canCompare}
        onClick={() => void state.runAnnotationDiff(effectiveKeyA, effectiveKeyB)}
      >
        Compare columns
      </button>

      {result && (
        <div style={{ marginTop: '0.75rem' }}>
          <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap', marginBottom: '0.75rem' }}>
            <div className="panel" style={{ padding: '0.5rem 0.75rem', flex: '1 1 100px' }}>
              <p className="muted" style={{ margin: 0, fontSize: '0.7rem' }}>Total cells</p>
              <p style={{ margin: 0, fontWeight: 600 }}>{result.total_cells.toLocaleString()}</p>
            </div>
            <div className="panel" style={{ padding: '0.5rem 0.75rem', flex: '1 1 100px', color: '#e65100' }}>
              <p className="muted" style={{ margin: 0, fontSize: '0.7rem' }}>Changed</p>
              <p style={{ margin: 0, fontWeight: 600 }}>
                {result.changed_cells.toLocaleString()} ({Math.round(result.changed_cells / result.total_cells * 100)}%)
              </p>
            </div>
            <div className="panel" style={{ padding: '0.5rem 0.75rem', flex: '1 1 100px', color: '#2e7d32' }}>
              <p className="muted" style={{ margin: 0, fontSize: '0.7rem' }}>Unchanged</p>
              <p style={{ margin: 0, fontWeight: 600 }}>{result.unchanged_cells.toLocaleString()}</p>
            </div>
          </div>

          {changedTransitions.length > 0 && (
            <>
              <h3>Label transitions (top changes)</h3>
              <table style={{ width: '100%', fontSize: '0.75rem', borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--border)' }}>
                    <th style={{ textAlign: 'left', padding: '2px 4px' }}>{result.key_a}</th>
                    <th style={{ textAlign: 'left', padding: '2px 4px' }}>→ {result.key_b}</th>
                    <th style={{ textAlign: 'right', padding: '2px 4px' }}>Cells</th>
                  </tr>
                </thead>
                <tbody>
                  {changedTransitions
                    .sort((a, b) => b.count - a.count)
                    .slice(0, 30)
                    .map((t, i) => (
                      <tr key={i} style={{ borderBottom: '1px solid var(--border-subtle, #eee)' }}>
                        <td className="mono" style={{ padding: '2px 4px' }}>{t.label_a || '(empty)'}</td>
                        <td className="mono" style={{ padding: '2px 4px', color: '#1976d2' }}>{t.label_b || '(empty)'}</td>
                        <td style={{ textAlign: 'right', padding: '2px 4px' }}>{t.count.toLocaleString()}</td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </>
          )}
        </div>
      )}
    </section>
  )
}
