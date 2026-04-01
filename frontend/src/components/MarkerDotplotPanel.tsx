import { useStore } from '../app/store'

export default function MarkerDotplotPanel() {
  const state = useStore((store) => ({
    dotplotResult: store.dotplotResult
  }))

  if (!state.dotplotResult) {
    return null
  }

  return (
    <section className="panel dotplot-panel">
      <div className="cluster-label-header">
        <div>
          <h2>Marker Dotplot</h2>
          <p className="muted">
            Rows: <span className="mono">{state.dotplotResult.display_group_key}</span>
            {' | '}
            Genes: {state.dotplotResult.genes.join(', ')}
          </p>
        </div>
      </div>
      {state.dotplotResult.missing_genes.length > 0 ? (
        <p className="muted">
          Missing genes skipped: {state.dotplotResult.missing_genes.join(', ')}
        </p>
      ) : null}
      {state.dotplotResult.saved_path ? (
        <p className="muted">
          Saved to <span className="mono">{state.dotplotResult.saved_path}</span>
        </p>
      ) : null}
      <img
        className="dotplot-image"
        src={`data:image/png;base64,${state.dotplotResult.image_base64}`}
        alt="Marker gene dotplot"
      />
    </section>
  )
}
