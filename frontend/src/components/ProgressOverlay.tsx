import { useEffect, useRef, useState } from 'react'
import { useStore, type TrackedTask } from '../app/store'

const SHOW_DELAY_MS = 300
const COMPLETE_HOLD_MS = 500
const MAX_ANIMATED_PCT = 92

export default function ProgressOverlay() {
  const { trackedTask, stopCurrentTask } = useStore((state) => ({
    trackedTask: state.trackedTask,
    stopCurrentTask: state.stopCurrentTask
  }))
  const [now, setNow] = useState(() => Date.now())
  const [visible, setVisible] = useState(false)
  const [completing, setCompleting] = useState(false)
  const lastTaskRef = useRef<TrackedTask | undefined>(undefined)
  const wasVisibleRef = useRef(false)

  useEffect(() => {
    wasVisibleRef.current = visible
  }, [visible])

  useEffect(() => {
    if (trackedTask) {
      lastTaskRef.current = trackedTask
      setCompleting(false)
      // Avoid flicker for fast/cached operations: only pop out if still running
      // after a short delay.
      const showTimer = window.setTimeout(() => setVisible(true), SHOW_DELAY_MS)
      const tick = window.setInterval(() => setNow(Date.now()), 100)
      return () => {
        window.clearTimeout(showTimer)
        window.clearInterval(tick)
      }
    }
    // Task just finished — if the bar was already showing, hold at 100% briefly
    // before dismissing so the user sees it actually completed.
    if (wasVisibleRef.current) {
      setCompleting(true)
      const hideTimer = window.setTimeout(() => {
        setVisible(false)
        setCompleting(false)
      }, COMPLETE_HOLD_MS)
      return () => window.clearTimeout(hideTimer)
    }
    setVisible(false)
    return undefined
  }, [trackedTask])

  const task = trackedTask ?? lastTaskRef.current
  if (!visible || !task) {
    return null
  }

  const elapsedMs = now - task.startedAt
  const pct = completing ? 100 : Math.min(MAX_ANIMATED_PCT, (elapsedMs / task.estimatedMs) * 100)
  const elapsedSeconds = (elapsedMs / 1000).toFixed(1)

  return (
    <div className="progress-overlay-backdrop">
      <div className={`progress-overlay${completing ? ' is-complete' : ''}`} role="status" aria-live="polite">
        <div className="progress-overlay-header">
          <span>{completing ? `${task.label} — done` : task.label}</span>
          {!completing ? (
            <button className="button button-secondary button-inline" onClick={stopCurrentTask}>
              Cancel
            </button>
          ) : null}
        </div>
        <div className="progress-bar-track">
          <div className="progress-bar-fill" style={{ width: `${pct}%` }} />
        </div>
        <div className="progress-overlay-footer">
          <span>{elapsedSeconds}s elapsed</span>
          <span>{completing ? '100%' : pct < MAX_ANIMATED_PCT ? `~${Math.round(pct)}%` : 'almost done…'}</span>
        </div>
      </div>
    </div>
  )
}
