import { useEffect, useRef, useState, type MouseEvent } from 'react'
import AnnotationDiffPanel from './components/AnnotationDiffPanel'
import ClusterLabelEditor from './components/ClusterLabelEditor'
import DEPanel from './components/DEPanel'
import GenePanel from './components/GenePanel'
import LiveSessionBanner from './components/LiveSessionBanner'
import MarkerDotplotPanel from './components/MarkerDotplotPanel'
import ObjectBrowser from './components/ObjectBrowser'
import ObsMetadataPanel from './components/ObsMetadataPanel'
import ProjectDashboard from './components/ProjectDashboard'
import SessionSidebar from './components/SessionSidebar'
import SpatialCanvas from './components/SpatialCanvas'
import UmapCanvas from './components/UmapCanvas'
import { useStore } from './app/store'

export default function App() {
  const mainStageRef = useRef<HTMLElement | null>(null)
  const [scrollRail, setScrollRail] = useState({
    thumbHeight: 0,
    thumbTop: 0
  })
  const {
    scanFolder,
    loadGlobalMetadata,
    metadata,
    globalMetadata,
    busy,
    busyMessage,
    error,
    activeViewMode,
    setActiveViewMode,
    globalHighlight,
    stopCurrentTask,
    loadDashboard,
    dashboardVisible,
    downloadExportAnnotations,
    sessionId,
    selectedObjectId
  } = useStore((state) => ({
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
    stopCurrentTask: state.stopCurrentTask,
    loadDashboard: state.loadDashboard,
    dashboardVisible: state.dashboardVisible,
    downloadExportAnnotations: state.downloadExportAnnotations,
    sessionId: state.sessionId,
    selectedObjectId: state.selectedObjectId
  }))

  const activeMetadata = activeViewMode === 'global' ? globalMetadata : metadata
  const hasSpatial = metadata?.has_spatial ?? false

  useEffect(() => {
    void scanFolder()
    void loadGlobalMetadata()
  }, [loadGlobalMetadata, scanFolder])

  useEffect(() => {
    const element = mainStageRef.current
    if (!element) {
      return
    }

    const updateScrollRail = () => {
      const clientHeight = element.clientHeight
      const scrollHeight = element.scrollHeight
      const trackHeight = Math.max(clientHeight - 32, 0)
      if (trackHeight <= 0) {
        setScrollRail({ thumbHeight: 0, thumbTop: 0 })
        return
      }
      if (scrollHeight <= clientHeight + 1) {
        setScrollRail({ thumbHeight: trackHeight, thumbTop: 0 })
        return
      }
      const thumbHeight = Math.max(44, trackHeight * (clientHeight / scrollHeight))
      const maxThumbTop = Math.max(trackHeight - thumbHeight, 0)
      const maxScrollTop = Math.max(scrollHeight - clientHeight, 1)
      const thumbTop = (element.scrollTop / maxScrollTop) * maxThumbTop
      setScrollRail({ thumbHeight, thumbTop })
    }

    updateScrollRail()
    const observer = new ResizeObserver(() => updateScrollRail())
    observer.observe(element)
    window.addEventListener('resize', updateScrollRail)
    element.addEventListener('scroll', updateScrollRail, { passive: true })
    const frameId = window.requestAnimationFrame(updateScrollRail)

    return () => {
      observer.disconnect()
      window.removeEventListener('resize', updateScrollRail)
      element.removeEventListener('scroll', updateScrollRail)
      window.cancelAnimationFrame(frameId)
    }
  }, [activeViewMode, busy, busyMessage, error, globalMetadata, metadata])

  const handleMainStageRailClick = (event: MouseEvent<HTMLDivElement>) => {
    const element = mainStageRef.current
    if (!element) {
      return
    }
    const rect = event.currentTarget.getBoundingClientRect()
    const trackHeight = Math.max(rect.height, 1)
    const maxScrollTop = Math.max(element.scrollHeight - element.clientHeight, 0)
    const desiredThumbCenter = event.clientY - rect.top
    const desiredThumbTop = Math.max(0, desiredThumbCenter - scrollRail.thumbHeight / 2)
    const maxThumbTop = Math.max(trackHeight - scrollRail.thumbHeight, 1)
    const ratio = Math.min(1, desiredThumbTop / maxThumbTop)
    element.scrollTop = ratio * maxScrollTop
  }

  return (
    <main className="app-shell">
      <aside className="left-rail">
        <ObjectBrowser />
        <SessionSidebar />
      </aside>
      <div className="main-stage-shell">
        <section className="main-stage" ref={mainStageRef}>
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
              {selectedObjectId ? (
                <div style={{ display: 'flex', gap: '0.25rem' }}>
                  <button
                    className="button button-secondary button-inline"
                    title="Project dashboard"
                    onClick={() => void loadDashboard()}
                  >
                    Dashboard
                  </button>
                  <button
                    className="button button-secondary button-inline"
                    title="Export annotations as CSV"
                    onClick={() => downloadExportAnnotations('csv')}
                  >
                    Export CSV
                  </button>
                </div>
              ) : null}
            </div>
          </header>

          {/* F-03: Live session restore banner */}
          <LiveSessionBanner />

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

          {/* F-06: Spatial view — only shown for lineage objects with spatial coords */}
          {activeViewMode === 'lineage' && hasSpatial ? <SpatialCanvas /> : null}

          <ClusterLabelEditor />
          <MarkerDotplotPanel />

          {/* F-04/F-13: Obs metadata coloring */}
          {activeViewMode === 'lineage' ? <ObsMetadataPanel /> : null}

          {/* F-08: Differential expression */}
          {activeViewMode === 'lineage' ? <DEPanel /> : null}

          {/* F-15: Annotation diff */}
          {activeViewMode === 'lineage' ? <AnnotationDiffPanel /> : null}
        </section>
        <div className="main-stage-scroll-rail" onClick={handleMainStageRailClick} role="presentation">
          <div
            className="main-stage-scroll-thumb"
            style={{
              height: `${Math.max(scrollRail.thumbHeight, 18)}px`,
              transform: `translateY(${scrollRail.thumbTop}px)`
            }}
          />
        </div>
      </div>
      <GenePanel />
      {/* F-10: Project dashboard modal */}
      <ProjectDashboard />
    </main>
  )
}
