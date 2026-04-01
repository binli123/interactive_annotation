import { useEffect } from 'react'
import ClusterLabelEditor from './components/ClusterLabelEditor'
import GenePanel from './components/GenePanel'
import MarkerDotplotPanel from './components/MarkerDotplotPanel'
import ObjectBrowser from './components/ObjectBrowser'
import SessionSidebar from './components/SessionSidebar'
import UmapCanvas from './components/UmapCanvas'
import { useStore } from './app/store'

export default function App() {
  const { scanFolder, metadata, busy, error } = useStore((state) => ({
    scanFolder: state.scanFolder,
    metadata: state.metadata,
    busy: state.busy,
    error: state.error
  }))

  useEffect(() => {
    void scanFolder()
  }, [scanFolder])

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
              {metadata
                ? `${metadata.lineage_name} | ${metadata.shape[0].toLocaleString()} cells | ${metadata.shape[1].toLocaleString()} genes`
                : 'Load a lineage object to begin.'}
            </p>
          </div>
          <div className="status-row">
            {busy ? <span className="status-pill">Working</span> : null}
            {error ? <span className="status-pill status-error">{error}</span> : null}
          </div>
        </header>
        <UmapCanvas />
        <ClusterLabelEditor />
        <MarkerDotplotPanel />
      </section>
      <GenePanel />
    </main>
  )
}
