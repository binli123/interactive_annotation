import { useStore } from '../app/store'

export default function ProjectDashboard() {
  const state = useStore((store) => ({
    dashboardData: store.dashboardData,
    dashboardVisible: store.dashboardVisible,
    loadDashboard: store.loadDashboard,
    setDashboardVisible: store.setDashboardVisible,
    selectObject: store.selectObject,
    selectedObjectId: store.selectedObjectId,
    busy: store.busy
  }))

  if (!state.dashboardVisible) return null

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.5)',
        zIndex: 100,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center'
      }}
      onClick={() => state.setDashboardVisible(false)}
    >
      <div
        style={{
          background: 'var(--bg, #fff)',
          borderRadius: 8,
          padding: '1.5rem',
          minWidth: 600,
          maxWidth: 900,
          maxHeight: '80vh',
          overflowY: 'auto',
          boxShadow: '0 8px 32px rgba(0,0,0,0.25)'
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="cluster-label-header" style={{ marginBottom: '1rem' }}>
          <h2 style={{ margin: 0 }}>Project Dashboard</h2>
          <button className="button button-secondary" onClick={() => state.setDashboardVisible(false)}>
            Close
          </button>
        </div>

        {!state.dashboardData ? (
          <p className="muted">Loading…</p>
        ) : (
          <>
            <div style={{ display: 'flex', gap: '1rem', marginBottom: '1rem', flexWrap: 'wrap' }}>
              <div className="panel" style={{ flex: '1 1 140px', padding: '0.75rem', minWidth: 140 }}>
                <p className="muted" style={{ margin: 0, fontSize: '0.75rem' }}>Total objects</p>
                <p style={{ margin: 0, fontSize: '1.5rem', fontWeight: 600 }}>{state.dashboardData.length}</p>
              </div>
              <div className="panel" style={{ flex: '1 1 140px', padding: '0.75rem', minWidth: 140 }}>
                <p className="muted" style={{ margin: 0, fontSize: '0.75rem' }}>Total cells</p>
                <p style={{ margin: 0, fontSize: '1.5rem', fontWeight: 600 }}>
                  {state.dashboardData.reduce((s, r) => s + (r.n_cells ?? 0), 0).toLocaleString()}
                </p>
              </div>
              <div className="panel" style={{ flex: '1 1 140px', padding: '0.75rem', minWidth: 140 }}>
                <p className="muted" style={{ margin: 0, fontSize: '0.75rem' }}>Annotated objects</p>
                <p style={{ margin: 0, fontSize: '1.5rem', fontWeight: 600 }}>
                  {state.dashboardData.filter((r) => (r.annotation_fraction ?? 0) > 0).length}
                </p>
              </div>
              <div className="panel" style={{ flex: '1 1 140px', padding: '0.75rem', minWidth: 140 }}>
                <p className="muted" style={{ margin: 0, fontSize: '0.75rem' }}>Avg annotation</p>
                <p style={{ margin: 0, fontSize: '1.5rem', fontWeight: 600 }}>
                  {(() => {
                    const fracs = state.dashboardData.filter((r) => r.annotation_fraction != null).map((r) => r.annotation_fraction!)
                    return fracs.length ? (fracs.reduce((a, b) => a + b, 0) / fracs.length * 100).toFixed(0) + '%' : '—'
                  })()}
                </p>
              </div>
            </div>

            <table style={{ width: '100%', fontSize: '0.8rem', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ borderBottom: '2px solid var(--border)' }}>
                  <th style={{ textAlign: 'left', padding: '4px 6px' }}>Lineage</th>
                  <th style={{ textAlign: 'right', padding: '4px 6px' }}>Cells</th>
                  <th style={{ textAlign: 'right', padding: '4px 6px' }}>Clusters</th>
                  <th style={{ textAlign: 'right', padding: '4px 6px' }}>Annotated</th>
                  <th style={{ textAlign: 'left', padding: '4px 6px' }}>Coverage</th>
                  <th style={{ padding: '4px 6px' }}></th>
                </tr>
              </thead>
              <tbody>
                {state.dashboardData.map((row) => {
                  const pct = row.annotation_fraction != null ? Math.round(row.annotation_fraction * 100) : null
                  const isSelected = row.object_id === state.selectedObjectId
                  return (
                    <tr
                      key={row.object_id}
                      style={{
                        borderBottom: '1px solid var(--border-subtle, #eee)',
                        background: isSelected ? 'var(--highlight-bg, #f0f7ff)' : undefined
                      }}
                    >
                      <td style={{ padding: '4px 6px', fontWeight: isSelected ? 600 : undefined }}>
                        {row.lineage_name}
                      </td>
                      <td style={{ textAlign: 'right', padding: '4px 6px' }}>
                        {row.n_cells?.toLocaleString() ?? '—'}
                      </td>
                      <td style={{ textAlign: 'right', padding: '4px 6px' }}>{row.n_clusters ?? '—'}</td>
                      <td style={{ textAlign: 'right', padding: '4px 6px' }}>
                        {row.n_annotated?.toLocaleString() ?? '—'}
                      </td>
                      <td style={{ padding: '4px 6px', minWidth: 100 }}>
                        {pct != null ? (
                          <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                            <div
                              style={{
                                flex: 1,
                                height: 6,
                                background: 'var(--border-subtle, #eee)',
                                borderRadius: 3,
                                overflow: 'hidden'
                              }}
                            >
                              <div
                                style={{
                                  width: `${pct}%`,
                                  height: '100%',
                                  background: pct === 100 ? '#2e7d32' : pct > 50 ? '#1976d2' : '#e65100',
                                  borderRadius: 3
                                }}
                              />
                            </div>
                            <span style={{ minWidth: 30, textAlign: 'right', fontSize: '0.75rem' }}>
                              {pct}%
                            </span>
                          </div>
                        ) : (
                          <span className="muted">—</span>
                        )}
                      </td>
                      <td style={{ padding: '4px 6px' }}>
                        <button
                          className="button button-secondary"
                          style={{ fontSize: '0.7rem', padding: '2px 8px' }}
                          onClick={() => {
                            void state.selectObject(row.object_id)
                            state.setDashboardVisible(false)
                          }}
                        >
                          Open
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </>
        )}
      </div>
    </div>
  )
}
