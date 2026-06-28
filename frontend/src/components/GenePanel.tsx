import { useMemo, useState } from 'react'
import { useStore } from '../app/store'

export default function GenePanel() {
  const [dragIndex, setDragIndex] = useState<number | null>(null)
  const [genePasteValue, setGenePasteValue] = useState('')
  const [pasteFeedback, setPasteFeedback] = useState<string | null>(null)
  const state = useStore((store) => ({
    activeViewMode: store.activeViewMode,
    geneCatalog: store.geneCatalog,
    globalGeneCatalog: store.globalGeneCatalog,
    geneSearch: store.geneSearch,
    selectedGenes: store.selectedGenes,
    activeHighlightedGene: store.activeHighlightedGene,
    favoriteGenes: store.favoriteGenes,
    clusterLabelEditor: store.clusterLabelEditor,
    clusterVisibility: store.clusterVisibility,
    markerDiscoveryTargets: store.markerDiscoveryTargets,
    markerDiscoveryTopN: store.markerDiscoveryTopN,
    markerDiscoveryResult: store.markerDiscoveryResult,
    setGeneSearch: store.setGeneSearch,
    addSelectedGenes: store.addSelectedGenes,
    toggleGeneSelected: store.toggleGeneSelected,
    clearSelectedGenes: store.clearSelectedGenes,
    setActiveHighlightedGene: store.setActiveHighlightedGene,
    toggleFavoriteGene: store.toggleFavoriteGene,
    reorderSelectedGenes: store.reorderSelectedGenes,
    toggleMarkerDiscoveryTarget: store.toggleMarkerDiscoveryTarget,
    setMarkerDiscoveryTopN: store.setMarkerDiscoveryTopN,
    discoverMarkers: store.discoverMarkers,
    colorBySelectedGene: store.colorBySelectedGene,
    restoreClusterColorView: store.restoreClusterColorView,
    previewDotplot: store.previewDotplot,
    saveDotplot: store.saveDotplot,
    busy: store.busy
  }))

  const geneCatalog = state.activeViewMode === 'global' ? state.globalGeneCatalog : state.geneCatalog

  const favoriteSet = useMemo(() => new Set(state.favoriteGenes), [state.favoriteGenes])
  const selectedSet = useMemo(() => new Set(state.selectedGenes), [state.selectedGenes])
  const geneLookup = useMemo(
    () => new Map((geneCatalog?.genes ?? []).map((gene) => [gene.toLowerCase(), gene] as const)),
    [geneCatalog?.genes]
  )
  const effectiveHighlightedGene =
    state.activeHighlightedGene && selectedSet.has(state.activeHighlightedGene)
      ? state.activeHighlightedGene
      : state.selectedGenes.length === 1
        ? state.selectedGenes[0]
        : undefined
  const filteredGenes = useMemo(() => {
    const query = state.geneSearch.trim().toLowerCase()
    const genes = geneCatalog?.genes ?? []
    return genes
      .filter((gene) => (query ? gene.toLowerCase().includes(query) : true))
      .sort((left, right) => {
        const leftFavorite = favoriteSet.has(left) ? 1 : 0
        const rightFavorite = favoriteSet.has(right) ? 1 : 0
        if (leftFavorite !== rightFavorite) {
          return rightFavorite - leftFavorite
        }
        return left.localeCompare(right)
      })
  }, [favoriteSet, geneCatalog?.genes, state.geneSearch])

  function applyGenePaste(rawValue: string) {
    const tokens = rawValue
      .split(/[\s,;|]+/)
      .map((value) => value.trim())
      .filter(Boolean)
    if (tokens.length === 0) {
      setPasteFeedback('No gene symbols were found in the pasted text.')
      return
    }

    const matched: string[] = []
    const missing: string[] = []
    const seen = new Set<string>()
    for (const token of tokens) {
      const match = geneLookup.get(token.toLowerCase())
      if (match) {
        if (!seen.has(match)) {
          matched.push(match)
          seen.add(match)
        }
      } else {
        missing.push(token)
      }
    }

    if (matched.length > 0) {
      state.addSelectedGenes(matched)
    }
    setPasteFeedback(
      `${matched.length} matched${missing.length > 0 ? `, ${missing.length} not found` : ''}.`
    )
    setGenePasteValue('')
  }

  if (!geneCatalog) {
    return (
      <aside className="right-rail">
        <section className="panel">
          <h2>Gene Examination</h2>
          <p className="muted">Load a valid object to inspect genes.</p>
        </section>
      </aside>
    )
  }

  return (
    <aside className="right-rail">
      <section className="panel gene-panel">
        <div className="cluster-label-header">
          <div>
            <h2>Gene Examination</h2>
            <p className="muted">
              {geneCatalog.genes.length.toLocaleString()} genes in {state.activeViewMode === 'global' ? 'global object' : 'lineage object'}
            </p>
          </div>
          <button className="button button-secondary" onClick={state.clearSelectedGenes}>
            Uncheck all genes
          </button>
        </div>

        <label className="field">
          <span>Search genes</span>
          <input
            value={state.geneSearch}
            onChange={(event) => state.setGeneSearch(event.target.value)}
            placeholder="Type a gene symbol"
          />
        </label>

        <label className="field">
          <span>Paste gene list</span>
          <textarea
            value={genePasteValue}
            onChange={(event) => setGenePasteValue(event.target.value)}
            onPaste={(event) => {
              const pasted = event.clipboardData.getData('text')
              if (!pasted) {
                return
              }
              event.preventDefault()
              applyGenePaste(pasted)
            }}
            rows={3}
            placeholder="Paste genes separated by commas, spaces, tabs, semicolons, or new lines"
          />
        </label>
        <div className="button-row gene-paste-actions">
          <button
            className="button button-secondary"
            type="button"
            onClick={() => applyGenePaste(genePasteValue)}
            disabled={genePasteValue.trim().length === 0}
          >
            Check pasted genes
          </button>
          <button
            className="button button-secondary"
            type="button"
            onClick={() => {
              setGenePasteValue('')
              setPasteFeedback(null)
            }}
            disabled={genePasteValue.length === 0 && !pasteFeedback}
          >
            Clear paste box
          </button>
        </div>
        {pasteFeedback ? <p className="muted">{pasteFeedback}</p> : null}

        <div className="selected-gene-block">
          <div className="cluster-label-header">
            <div>
              <h3>Selected Genes</h3>
              <p className="muted">{state.selectedGenes.length} checked</p>
            </div>
          </div>
          {state.selectedGenes.length === 0 ? (
            <p className="muted">Check genes from the list below. Drag selected genes here to rearrange their dotplot order.</p>
          ) : (
            <div className="selected-gene-list">
              {state.selectedGenes.map((gene, index) => (
                <div
                  key={gene}
                  className="selected-gene-chip"
                  draggable
                  onDragStart={() => setDragIndex(index)}
                  onDragOver={(event) => event.preventDefault()}
                  onDrop={() => {
                    if (dragIndex === null) {
                      return
                    }
                    state.reorderSelectedGenes(dragIndex, index)
                    setDragIndex(null)
                  }}
                  onDragEnd={() => setDragIndex(null)}
                >
                  <button
                    className={`chip-highlight-toggle ${effectiveHighlightedGene === gene ? 'is-active' : ''}`}
                    type="button"
                    onClick={() => state.setActiveHighlightedGene(gene)}
                    aria-label={
                      effectiveHighlightedGene === gene
                        ? `${gene} is the active highlighted gene`
                        : `Use ${gene} for UMAP gene coloring`
                    }
                    title={
                      effectiveHighlightedGene === gene
                        ? 'Active gene for UMAP coloring'
                        : 'Use this gene for UMAP coloring'
                    }
                  />
                  <span className="mono">{gene}</span>
                  <button className="chip-remove" onClick={() => state.toggleGeneSelected(gene)}>
                    x
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="button-row gene-action-row">
          <button
            className="button"
            disabled={state.busy || !effectiveHighlightedGene}
            onClick={() => void state.colorBySelectedGene()}
          >
            Color UMAP by gene
          </button>
          <button
            className="button"
            disabled={state.busy || state.selectedGenes.length === 0}
            onClick={() => void state.previewDotplot()}
          >
            Preview dotplot
          </button>
        </div>
        {state.selectedGenes.length > 1 && !effectiveHighlightedGene ? (
          <p className="muted">Choose one checked gene in Selected Genes to drive UMAP coloring.</p>
        ) : null}
        <button className="button button-secondary gene-save-button" onClick={state.restoreClusterColorView}>
          Restore cluster colors
        </button>
        <button
          className="button button-secondary gene-save-button"
          disabled={state.busy || state.selectedGenes.length === 0}
          onClick={() => void state.saveDotplot()}
        >
          Save dotplot beside object
        </button>

        <div className="gene-list">
          {filteredGenes.map((gene) => (
            <label key={gene} className="gene-row">
              <input
                type="checkbox"
                checked={selectedSet.has(gene)}
                onChange={() => state.toggleGeneSelected(gene)}
              />
              <span className="mono gene-name">{gene}</span>
              <button
                className={`heart-button ${favoriteSet.has(gene) ? 'is-active' : ''}`}
                onClick={(event) => {
                  event.preventDefault()
                  state.toggleFavoriteGene(gene)
                }}
                aria-label={favoriteSet.has(gene) ? `Unfavorite ${gene}` : `Favorite ${gene}`}
                title={favoriteSet.has(gene) ? 'Favorite gene' : 'Mark as favorite'}
              >
                {favoriteSet.has(gene) ? '♥' : '♡'}
              </button>
            </label>
          ))}
        </div>

        {state.activeViewMode === 'lineage' ? (
          <section className="marker-discovery-panel">
          <div className="cluster-label-header">
            <div>
              <h3>Marker Discovery</h3>
              <p className="muted">Uses only clusters checked in Cluster Names as the analysis universe.</p>
            </div>
          </div>
          <label className="field">
            <span>Candidate genes (N)</span>
            <input
              type="number"
              min="1"
              max="200"
              value={state.markerDiscoveryTopN}
              onChange={(event) => state.setMarkerDiscoveryTopN(Number(event.target.value))}
            />
          </label>
          <div className="marker-target-list">
            {state.clusterLabelEditor?.rows
              .filter((row) => state.clusterVisibility[row.cluster_id] ?? true)
              .map((row) => (
                <label key={row.cluster_id} className="gene-row">
                  <input
                    type="checkbox"
                    checked={state.markerDiscoveryTargets.includes(row.cluster_id)}
                    onChange={() => state.toggleMarkerDiscoveryTarget(row.cluster_id)}
                  />
                  <span className="mono gene-name">{row.cluster_id}</span>
                  <span className="small">{row.n_cells.toLocaleString()}</span>
                </label>
              ))}
          </div>
          <button className="button" disabled={state.busy} onClick={() => void state.discoverMarkers()}>
            Discover marker genes
          </button>
          {state.markerDiscoveryResult ? (
            <p className="muted">
              Added candidates: {state.markerDiscoveryResult.candidate_genes.join(', ') || 'none'}
            </p>
          ) : null}
          </section>
        ) : (
          <section className="marker-discovery-panel">
            <div className="cluster-label-header">
              <div>
                <h3>Marker Discovery</h3>
                <p className="muted">Marker discovery is available only in Lineage View.</p>
              </div>
            </div>
          </section>
        )}
      </section>
    </aside>
  )
}
