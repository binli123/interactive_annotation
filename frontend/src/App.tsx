import { useEffect } from 'react'
import ClusterLabelEditor from './components/ClusterLabelEditor'
import GenePanel from './components/GenePanel'
import MarkerDotplotPanel from './components/MarkerDotplotPanel'
import ObjectBrowser from './components/ObjectBrowser'
import SessionSidebar from './components/SessionSidebar'
import UmapCanvas from './components/UmapCanvas'
import { useStore } from './app/store'

export default function App() {
  const { scanFolder, loadGlobalMetadata, metadata, globalMetadata, busy, busyMessage, error, activeViewMode, setActiveViewMode, globalHighlight, stopCurrentTask } = useStore((state) => ({
    scanFolder: state.scanFolder,
    loadGlobalMetadata: state.loadGlobalMetadata,
    metadata: state.metadata,
    globalMetadata: state.globalMetadata,
    busy: state.busy,
    busyMessage: state.busyMessage,
    error: state.error,
    activeViewMode: state.activeViewMode,
    setActiveViewMode: state.setActiveViewMode,
    globalHighlight: state.globalHighlight,
    stopCurrentTask: state.stopCurrentTask
  }))

  const activeMetadata = activeViewMode === 'global' ? globalMetadata : metadata

  useEffect(() => {
    void scanFolder()
    void loadGlobalMetadata()
  }, [loadGlobalMetadata, scanFolder])

  return (
    <main className="app-shell">
      <aside className="left-rail">
        <ObjectBrowser />
        <SessionSidebar />
      </aside>
      <section className="main-stage">
        <header className="stage-header">
          <div>
            <h1>Interactive Lineage Reannotation</h1>
            <p className="muted">
              {activeMetadata
                ? `${activeMetadata.lineage_name} | ${activeMetadata.shape[0].toLocaleString()} cells | ${activeMetadata.shape[1].toLocaleString()} genes`
                : 'Load a lineage object to begin.'}
            </p>
          </div>
          <div className="status-row">
            {busy ? <span className="status-pill">{busyMessage ? `Working: ${busyMessage}` : 'Working'}</span> : null}
            {busy ? (
              <button className="button button-secondary button-inline" onClick={stopCurrentTask}>
                Stop
              </button>
            ) : null}
            {globalHighlight ? <span className="status-pill">Global highlight active</span> : null}
            {error ? <span className="status-pill status-error">{error}</span> : null}
          </div>
        </header>
        <div className="panel view-mode-tabs">
          <button
            className={`tab-button ${activeViewMode === 'lineage' ? 'is-active' : ''}`}
            onClick={() => setActiveViewMode('lineage')}
          >
            Lineage View
          </button>
          <button
            className={`tab-button ${activeViewMode === 'global' ? 'is-active' : ''}`}
            onClick={() => setActiveViewMode('global')}
          >
            Global View
          </button>
        </div>
        <UmapCanvas mode={activeViewMode} />
        <ClusterLabelEditor />
        <MarkerDotplotPanel />
      </section>
      <GenePanel />
    </main>
  )
}
