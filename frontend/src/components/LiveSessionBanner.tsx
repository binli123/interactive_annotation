import { useStore } from '../app/store'

export default function LiveSessionBanner() {
  const state = useStore((store) => ({
    liveSessionInfo: store.liveSessionInfo,
    restoreLiveSession: store.restoreLiveSession,
    dismissLiveSession: store.dismissLiveSession,
    busy: store.busy
  }))

  const info = state.liveSessionInfo
  if (!info?.available) return null

  const labelSummary = Object.entries(info.labels ?? {})
    .map(([label, count]) => `${label}: ${count}`)
    .join(', ')

  return (
    <div
      style={{
        background: '#fff3e0',
        border: '1px solid #ff9800',
        borderRadius: 6,
        padding: '0.75rem 1rem',
        display: 'flex',
        alignItems: 'center',
        gap: '1rem',
        flexWrap: 'wrap',
        marginBottom: '0.5rem'
      }}
    >
      <div style={{ flex: 1 }}>
        <strong>Unsaved session found</strong>
        <p className="muted" style={{ margin: '2px 0 0' }}>
          {info.n_seed_cells?.toLocaleString()} seed cells · {info.n_polygons} polygon{info.n_polygons !== 1 ? 's' : ''}
          {labelSummary ? ` · ${labelSummary}` : ''}
          {info.has_propagation ? ' · propagation available' : ''}
        </p>
      </div>
      <div style={{ display: 'flex', gap: '0.5rem' }}>
        <button
          className="button"
          disabled={state.busy}
          onClick={() => void state.restoreLiveSession()}
        >
          Restore session
        </button>
        <button
          className="button button-secondary"
          onClick={() => void state.dismissLiveSession()}
        >
          Discard
        </button>
      </div>
    </div>
  )
}
