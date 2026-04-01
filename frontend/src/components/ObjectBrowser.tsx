import { useStore } from '../app/store'

function basename(path: string): string {
  const parts = path.split('/')
  return parts[parts.length - 1] || path
}

export default function ObjectBrowser() {
  const {
    folderPath,
    setFolderPath,
    scanFolder,
    objects,
    selectedObjectId,
    selectObject,
    busy
  } = useStore((state) => ({
    folderPath: state.folderPath,
    setFolderPath: state.setFolderPath,
    scanFolder: state.scanFolder,
    objects: state.objects,
    selectedObjectId: state.selectedObjectId,
    selectObject: state.selectObject,
    busy: state.busy
  }))

  return (
    <section className="panel">
      <h2>Objects</h2>
      <label className="field">
        <span>Lineage folder</span>
        <input
          value={folderPath}
          onChange={(event) => setFolderPath(event.target.value)}
          placeholder="/path/to/lineages"
        />
      </label>
      <button className="button" onClick={() => void scanFolder()} disabled={busy}>
        Scan
      </button>
      <label className="field">
        <span>Detected objects</span>
        <select
          value={selectedObjectId}
          onChange={(event) => void selectObject(event.target.value)}
          disabled={objects.length === 0 || busy}
        >
          {objects.map((object) => (
            <option key={object.object_id} value={object.object_id}>
              {object.lineage_name} | {basename(object.object_path)} ({object.n_cells ?? 'NA'} cells)
              {object.is_valid ? '' : ' [invalid]'}
            </option>
          ))}
        </select>
      </label>
      {objects.find((object) => object.object_id === selectedObjectId && !object.is_valid)?.validation_error ? (
        <p className="muted">
          {objects.find((object) => object.object_id === selectedObjectId)?.validation_error}
        </p>
      ) : null}
    </section>
  )
}
