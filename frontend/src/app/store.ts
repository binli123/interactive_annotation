import { create } from 'zustand'
import { abortActiveRequests, api } from './api'
import type {
  AnnotationDiffResponse,
  ClusterLabelEditorResponse,
  DEResponse,
  DotplotResponse,
  GeneCatalogResponse,
  LiveSessionResponse,
  MarkerDiscoveryResponse,
  MetadataResponse,
  MoveClusterPreviewResponse,
  MoveClusterResponse,
  MoveClusterUndoResponse,
  MoveClusterUndoStatusResponse,
  ObjectAnnotationCoverage,
  ObjectChangeUndoResponse,
  ObjectChangeUndoStatusResponse,
  ObjectCard,
  ObsColumnMeta,
  ObsValuesResponse,
  PolygonRecord,
  PromoteReannotLabelsResponse,
  PropagateResponse,
  ReferencePropagateResponse,
  SaveClusterLabelsResponse,
  SaveResponse,
  SessionSummary,
  UmapPoint,
  VisibleHighlightResponse
} from './types'

const defaultFolder =
  import.meta.env.VITE_DEFAULT_FOLDER ?? ''

const favoriteGenesStorageKey = 'interactive_annotation_favorite_genes'

function randomSessionId(): string {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return crypto.randomUUID()
  }
  return `session_${Math.random().toString(36).slice(2, 10)}`
}

function randomPolygonId(): string {
  return `polygon_${Math.random().toString(36).slice(2, 8)}`
}

function loadFavoriteGenes(): string[] {
  if (typeof window === 'undefined') {
    return []
  }
  try {
    const raw = window.localStorage.getItem(favoriteGenesStorageKey)
    if (!raw) {
      return []
    }
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed.filter((value): value is string => typeof value === 'string') : []
  } catch {
    return []
  }
}

function saveFavoriteGenes(genes: string[]) {
  if (typeof window === 'undefined') {
    return
  }
  window.localStorage.setItem(favoriteGenesStorageKey, JSON.stringify(genes))
}

function moveArrayItem(values: string[], fromIndex: number, toIndex: number): string[] {
  const next = [...values]
  const [item] = next.splice(fromIndex, 1)
  next.splice(toIndex, 0, item)
  return next
}

function preferredGlobalClusterKey(metadata?: MetadataResponse): string {
  if (!metadata) {
    return ''
  }
  if (metadata.cluster_keys.includes('final_valid_lineage')) {
    return 'final_valid_lineage'
  }
  return metadata.default_cluster_key ?? ''
}

function samePointSequence(left: UmapPoint[], right: UmapPoint[]): boolean {
  if (left.length !== right.length) {
    return false
  }
  for (let index = 0; index < left.length; index += 1) {
    if (left[index]?.index !== right[index]?.index) {
      return false
    }
  }
  return true
}

function effectiveHighlightedGene(
  selectedGenes: string[],
  activeHighlightedGene?: string
): string | undefined {
  if (activeHighlightedGene && selectedGenes.includes(activeHighlightedGene)) {
    return activeHighlightedGene
  }
  return selectedGenes.length === 1 ? selectedGenes[0] : undefined
}

// Rough, size-based duration estimates used only to animate the progress bar
// (calibrated against measured timings on this app's largest real lineage
// object, ~370k cells). The bar caps below 100% until the request actually
// resolves, so an inaccurate estimate makes the bar pause near the end rather
// than lie about completion.
function estimatePropagateMs(nCells: number, method: 'graph_diffusion' | 'knn_vote'): number {
  return method === 'graph_diffusion' ? 5000 + nCells * 0.02 : 6000 + nCells * 0.01
}

function estimateClusterSaveMs(nCells: number): number {
  return 800 + nCells * 0.01
}

function estimateGeneColorMs(nDisplayedCells: number): number {
  return 4000 + nDisplayedCells * 0.15
}

type PropagationScope =
  | 'polygon_only'
  | 'selected_clusters_only'
  | 'same_connected_neighborhood'
  | 'whole_lineage'

type ViewMode = 'lineage' | 'global'

type GlobalHighlightState = {
  sourceObjectId: string
  sourceClusterKey: string
  sourceClusterId: string
  sourceClusterName: string
  highlightedTotal: number
  highlightedDisplayed: number
}

type ColorMode = 'cluster' | 'annotation' | 'gene'

// Progress bar support for the three operations with real, size-dependent
// latency (propagate, cluster-name save, gene coloring). `estimatedMs` is a
// rough heuristic used only to animate the bar — the overlay always shows the
// true elapsed time alongside it and never reports 100% before the request
// actually resolves.
export type TrackedTask = {
  label: string
  startedAt: number
  estimatedMs: number
}

export type StoreState = {
  apiBase: string
  folderPath: string
  objects: ObjectCard[]
  selectedObjectId: string
  activeViewMode: ViewMode
  metadata?: MetadataResponse
  points: UmapPoint[]
  viewToken: string | null
  embeddingKey: string
  clusterKey: string
  maxPoints: number
  minPerCluster: number
  maxPerCluster: number
  globalMetadata?: MetadataResponse
  globalPoints: UmapPoint[]
  globalBasePoints: UmapPoint[]
  globalViewToken: string | null
  globalEmbeddingKey: string
  globalClusterKey: string
  globalMaxPoints: number
  globalMinPerCluster: number
  globalMaxPerCluster: number
  globalHighlight?: GlobalHighlightState
  moveClusterPreview?: MoveClusterPreviewResponse
  moveClusterResult?: MoveClusterResponse
  moveClusterUndoStatus?: MoveClusterUndoStatusResponse
  moveClusterUndoResult?: MoveClusterUndoResponse
  objectUndoStatus?: ObjectChangeUndoStatusResponse
  objectUndoResult?: ObjectChangeUndoResponse
  polygons: PolygonRecord[]
  draftVertices: number[][]
  draftPolygonId?: string
  isDrawing: boolean
  propagationMethod: 'graph_diffusion' | 'knn_vote'
  propagationScope: PropagationScope
  minScore: number
  minMargin: number
  annotateAll: boolean
  graphSmoothing: number
  pointSize: number
  pointOpacity: number
  polygonStrokeWidth: number
  flipHorizontal: boolean
  flipVertical: boolean
  sessionId: string
  sessionSummary?: SessionSummary
  propagationResult?: PropagateResponse
  saveResult?: SaveResponse
  savePromptOpen: boolean
  promoteReannotResult?: PromoteReannotLabelsResponse
  clusterLabelEditor?: ClusterLabelEditorResponse
  clusterLabelSaveResult?: SaveClusterLabelsResponse
  clusterVisibility: Record<string, boolean>
  referenceClusters: string[]
  sourceClusters: string[]
  referencePropagationName: string
  referencePropagationNeighbors: number
  referencePropagationResult?: ReferencePropagateResponse
  geneCatalog?: GeneCatalogResponse
  globalGeneCatalog?: GeneCatalogResponse
  geneSearch: string
  selectedGenes: string[]
  activeHighlightedGene?: string
  favoriteGenes: string[]
  geneColorGene?: string
  globalGeneColorGene?: string
  dotplotResult?: DotplotResponse
  markerDiscoveryTargets: string[]
  markerDiscoveryTopN: number
  markerDiscoveryResult?: MarkerDiscoveryResponse
  colorMode: ColorMode
  globalColorMode: Extract<ColorMode, 'cluster' | 'gene'>
  // F-04/F-13: obs metadata coloring
  obsColumns?: ObsColumnMeta[]
  activeObsColumn?: string
  obsColorValues: Record<number, number | string | null>
  // F-08: differential expression
  deResult?: DEResponse
  deTargetClusters: string[]
  deReferenceClusters: string[]
  // F-10: project dashboard
  dashboardData?: ObjectAnnotationCoverage[]
  dashboardVisible: boolean
  // F-15: annotation diff
  annotationDiffResult?: AnnotationDiffResponse
  // F-03: live session restore
  liveSessionInfo?: LiveSessionResponse
  hasGlobal: boolean
  busy: boolean
  busyMessage?: string
  trackedTask?: TrackedTask
  error?: string
  scanFolder: () => Promise<void>
  loadCapabilities: () => Promise<void>
  loadGlobalMetadata: () => Promise<void>
  selectObject: (objectId: string) => Promise<void>
  setActiveViewMode: (value: ViewMode) => void
  setFolderPath: (value: string) => void
  setEmbeddingKey: (value: string) => void
  setClusterKey: (value: string) => void
  setMaxPoints: (value: number) => void
  setMinPerCluster: (value: number) => void
  setMaxPerCluster: (value: number) => void
  setGlobalEmbeddingKey: (value: string) => void
  setGlobalClusterKey: (value: string) => void
  setGlobalMaxPoints: (value: number) => void
  setGlobalMinPerCluster: (value: number) => void
  setGlobalMaxPerCluster: (value: number) => void
  setColorMode: (value: ColorMode) => void
  setGlobalColorMode: (value: Extract<ColorMode, 'cluster' | 'gene'>) => void
  setPropagationMethod: (value: 'graph_diffusion' | 'knn_vote') => void
  setPropagationScope: (value: PropagationScope) => void
  setMinScore: (value: number) => void
  setMinMargin: (value: number) => void
  setAnnotateAll: (value: boolean) => void
  setGraphSmoothing: (value: number) => void
  setPointSize: (value: number) => void
  setPointOpacity: (value: number) => void
  setPolygonStrokeWidth: (value: number) => void
  setFlipHorizontal: (value: boolean) => void
  setFlipVertical: (value: boolean) => void
  setClusterVisibility: (clusterId: string, visible: boolean) => void
  restoreClusterColorView: () => void
  promoteReannotNewToCanonical: () => Promise<void>
  toggleReferenceCluster: (clusterId: string) => void
  toggleSourceCluster: (clusterId: string) => void
  setReferencePropagationName: (value: string) => void
  setReferencePropagationNeighbors: (value: number) => void
  runReferencePropagation: () => Promise<void>
  startDrawing: () => void
  stopDrawing: () => void
  addDraftVertex: (vertex: number[]) => void
  updateDraftVertex: (index: number, vertex: number[]) => void
  undoDraftVertex: () => void
  finalizeDraftPolygon: () => Promise<void>
  clearDraftPolygon: () => void
  editPolygonVertices: (polygonId: string) => void
  updatePolygon: (polygonId: string, updates: Partial<PolygonRecord>) => void
  removePolygon: (polygonId: string) => void
  clearPolygons: () => void
  loadUmap: (overrides?: {
    embeddingKey?: string
    clusterKey?: string
    geneName?: string | null
  }) => Promise<void>
  loadGlobalUmap: (overrides?: {
    embeddingKey?: string
    clusterKey?: string
  }) => Promise<void>
  refreshGlobalPointClusters: (clusterKey?: string) => Promise<void>
  highlightClusterInGlobal: (clusterId: string, clusterName: string) => Promise<void>
  restoreGlobalClusterColors: () => Promise<void>
  previewMoveCluster: (clusterId: string, destinationObjectId: string) => Promise<void>
  clearMoveClusterPreview: () => void
  moveClusterToObject: (clusterId: string, destinationObjectId: string) => Promise<void>
  loadMoveClusterUndoStatus: () => Promise<void>
  undoLatestMoveCluster: () => Promise<void>
  loadObjectUndoStatus: () => Promise<void>
  undoLatestObjectChange: () => Promise<void>
  refreshPointClusters: (clusterKey?: string) => Promise<void>
  propagate: () => Promise<void>
  refreshSessionSummary: () => Promise<void>
  saveSession: () => Promise<void>
  dismissSavePrompt: () => void
  resetPropagation: () => Promise<void>
  resetSession: () => Promise<void>
  loadClusterLabelEditor: () => Promise<void>
  updateClusterLabelName: (clusterId: string, displayName: string) => void
  saveClusterLabelEditor: () => Promise<void>
  loadGenes: () => Promise<void>
  loadGlobalGenes: () => Promise<void>
  setGeneSearch: (value: string) => void
  addSelectedGenes: (genes: string[]) => void
  toggleGeneSelected: (gene: string) => void
  clearSelectedGenes: () => void
  setActiveHighlightedGene: (gene?: string) => void
  toggleFavoriteGene: (gene: string) => void
  reorderSelectedGenes: (fromIndex: number, toIndex: number) => void
  toggleMarkerDiscoveryTarget: (clusterId: string) => void
  setMarkerDiscoveryTopN: (value: number) => void
  discoverMarkers: () => Promise<void>
  colorBySelectedGene: () => Promise<void>
  previewDotplot: () => Promise<void>
  saveDotplot: () => Promise<void>
  stopCurrentTask: () => void
  // F-04/F-13
  loadObsColumns: () => Promise<void>
  setActiveObsColumn: (column: string | undefined) => Promise<void>
  // F-08
  runDifferentialExpression: () => Promise<void>
  setDeTargetClusters: (clusters: string[]) => void
  setDeReferenceClusters: (clusters: string[]) => void
  toggleDeTargetCluster: (clusterId: string) => void
  toggleDeReferenceCluster: (clusterId: string) => void
  // F-09
  downloadExportAnnotations: (fmt: 'csv' | 'tsv' | 'json') => void
  // F-10
  loadDashboard: () => Promise<void>
  setDashboardVisible: (visible: boolean) => void
  // F-15
  runAnnotationDiff: (keyA: string, keyB: string) => Promise<void>
  // F-03
  checkLiveSession: () => Promise<void>
  restoreLiveSession: () => Promise<void>
  dismissLiveSession: () => Promise<void>
}

export const useStore = create<StoreState>((set, get) => ({
  apiBase: import.meta.env.VITE_API_BASE ?? '/api',
  folderPath: defaultFolder,
  objects: [],
  selectedObjectId: '',
  activeViewMode: 'lineage',
  metadata: undefined,
  points: [],
  viewToken: null,
  embeddingKey: '',
  clusterKey: '',
  maxPoints: 50000,
  minPerCluster: 250,
  maxPerCluster: 20000,
  globalMetadata: undefined,
  globalPoints: [],
  globalBasePoints: [],
  globalViewToken: null,
  globalEmbeddingKey: '',
  globalClusterKey: '',
  globalMaxPoints: 100000,
  globalMinPerCluster: 250,
  globalMaxPerCluster: 40000,
  globalHighlight: undefined,
  moveClusterPreview: undefined,
  moveClusterResult: undefined,
  moveClusterUndoStatus: undefined,
  moveClusterUndoResult: undefined,
  objectUndoStatus: undefined,
  objectUndoResult: undefined,
  polygons: [],
  draftVertices: [],
  draftPolygonId: undefined,
  isDrawing: false,
  propagationMethod: 'knn_vote',
  propagationScope: 'selected_clusters_only',
  minScore: 0.7,
  minMargin: 0.1,
  annotateAll: true,
  graphSmoothing: 0.15,
  pointSize: 0.88,
  pointOpacity: 0.8,
  polygonStrokeWidth: 1.25,
  flipHorizontal: false,
  flipVertical: false,
  sessionId: randomSessionId(),
  sessionSummary: undefined,
  propagationResult: undefined,
  saveResult: undefined,
  savePromptOpen: false,
  promoteReannotResult: undefined,
  clusterLabelEditor: undefined,
  clusterLabelSaveResult: undefined,
  clusterVisibility: {},
  referenceClusters: [],
  sourceClusters: [],
  referencePropagationName: 'new',
  referencePropagationNeighbors: 15,
  referencePropagationResult: undefined,
  geneCatalog: undefined,
  globalGeneCatalog: undefined,
  geneSearch: '',
  selectedGenes: [],
  activeHighlightedGene: undefined,
  favoriteGenes: loadFavoriteGenes(),
  geneColorGene: undefined,
  globalGeneColorGene: undefined,
  dotplotResult: undefined,
  markerDiscoveryTargets: [],
  markerDiscoveryTopN: 10,
  markerDiscoveryResult: undefined,
  colorMode: 'cluster',
  globalColorMode: 'cluster',
  obsColumns: undefined,
  activeObsColumn: undefined,
  obsColorValues: {},
  deResult: undefined,
  deTargetClusters: [],
  deReferenceClusters: [],
  dashboardData: undefined,
  dashboardVisible: false,
  annotationDiffResult: undefined,
  liveSessionInfo: undefined,
  hasGlobal: true,
  busy: false,
  busyMessage: undefined,
  trackedTask: undefined,
  error: undefined,

  async loadCapabilities() {
    try {
      const { has_global } = await api.getCapabilities(get().apiBase)
      set({ hasGlobal: has_global })
      if (!has_global && get().activeViewMode === 'global') {
        set({ activeViewMode: 'lineage' })
      }
      if (has_global) {
        await get().loadGlobalMetadata()
      }
    } catch {
      set({ hasGlobal: false })
    }
  },

  async scanFolder() {
    if (!get().folderPath) return
    set({ busy: true, busyMessage: 'Scanning objects', error: undefined })
    try {
      const objects = await api.scanFolder(get().apiBase, get().folderPath)
      const preferredObject = objects.find((object) => object.is_valid) ?? objects[0]
      set({
        objects,
        selectedObjectId: preferredObject?.object_id ?? '',
        busy: false,
        busyMessage: undefined
      })
      await Promise.all([
        get().loadMoveClusterUndoStatus(),
        get().loadObjectUndoStatus(),
        preferredObject?.is_valid ? get().selectObject(preferredObject.object_id) : Promise.resolve()
      ])
      if (!preferredObject?.is_valid && preferredObject) {
        set({
          error:
            preferredObject.validation_error ??
            `Object cannot be viewed interactively: ${preferredObject.object_path}`
        })
      }
    } catch (error) {
      set({
        busy: false,
        busyMessage: undefined,
        error: error instanceof Error ? error.message : String(error),
        objects: [],
        selectedObjectId: '',
        metadata: undefined,
        points: [],
        viewToken: null,
        polygons: [],
        sessionSummary: undefined,
        clusterLabelEditor: undefined,
        liveSessionInfo: undefined
      })
    }
  },

  async loadGlobalMetadata() {
    try {
      const metadata = await api.getGlobalMetadata(get().apiBase)
      const defaultClusterKey = preferredGlobalClusterKey(metadata)
      set((state) => ({
        globalMetadata: metadata,
        globalEmbeddingKey: state.globalEmbeddingKey || metadata.default_embedding_key,
        globalClusterKey: state.globalClusterKey || defaultClusterKey
      }))
      await Promise.all([
        get().loadGlobalUmap({
          embeddingKey: metadata.default_embedding_key,
          clusterKey: defaultClusterKey
        }),
        get().loadGlobalGenes()
      ])
    } catch (error) {
      set({
        globalMetadata: undefined,
        globalPoints: [],
        globalBasePoints: [],
        globalHighlight: undefined,
        globalGeneCatalog: undefined,
        error: error instanceof Error ? error.message : String(error)
      })
    }
  },

  async selectObject(objectId) {
    const hadGlobalHighlight = Boolean(get().globalHighlight)
    set({
      busy: true,
      busyMessage: 'Loading object',
      trackedTask: undefined,
      error: undefined,
      selectedObjectId: objectId,
      metadata: undefined,
      points: [],
      viewToken: null,
      polygons: [],
      draftVertices: [],
      draftPolygonId: undefined,
      isDrawing: false,
      colorMode: 'cluster',
      sessionId: randomSessionId(),
      sessionSummary: undefined,
      propagationResult: undefined,
      saveResult: undefined,
      savePromptOpen: false,
      promoteReannotResult: undefined,
      clusterLabelEditor: undefined,
      clusterLabelSaveResult: undefined,
      clusterVisibility: {},
      referenceClusters: [],
      sourceClusters: [],
      referencePropagationName: 'new',
      referencePropagationResult: undefined,
      propagationMethod: 'knn_vote',
      annotateAll: true,
      geneCatalog: undefined,
      geneSearch: '',
      selectedGenes: [],
      activeHighlightedGene: undefined,
      geneColorGene: undefined,
      dotplotResult: undefined,
      markerDiscoveryTargets: [],
      markerDiscoveryResult: undefined,
      moveClusterPreview: undefined,
      moveClusterResult: undefined,
      moveClusterUndoResult: undefined
    })
    try {
      const metadata = await api.getMetadata(get().apiBase, objectId)
      const nextClusterKey = metadata.default_cluster_key ?? ''
      const nextEmbeddingKey = metadata.default_embedding_key
      set({
        metadata,
        embeddingKey: nextEmbeddingKey,
        clusterKey: nextClusterKey
      })
      await Promise.all([
        api
          .getUmap(get().apiBase, objectId, {
            embedding_key: nextEmbeddingKey,
            cluster_key: nextClusterKey || null,
            gene_name: null,
            max_points: get().maxPoints,
            min_per_cluster: get().minPerCluster,
            max_per_cluster: get().maxPerCluster,
            random_seed: 13
          })
          .then((response) => set({ points: response.points, viewToken: response.view_token ?? null })),
        api
          .getClusterLabelEditor(get().apiBase, objectId, nextClusterKey)
          .then((editor) => {
            const nextVisibility = Object.fromEntries(
              editor.rows.map((row) => [row.cluster_id, get().clusterVisibility[row.cluster_id] ?? true])
            )
            set({
              clusterLabelEditor: editor,
              clusterLabelSaveResult: undefined,
              clusterVisibility: nextVisibility
            })
          }),
        api.getGenes(get().apiBase, objectId).then((geneCatalog) =>
          set((state) => ({
            geneCatalog,
            selectedGenes: state.selectedGenes.filter((gene) => geneCatalog.genes.includes(gene)),
            activeHighlightedGene: effectiveHighlightedGene(
              state.selectedGenes.filter((gene) => geneCatalog.genes.includes(gene)),
              state.activeHighlightedGene
            ),
            dotplotResult: undefined
          }))
        ),
        api.getMoveClusterUndoStatus(get().apiBase).then((moveClusterUndoStatus) => set({ moveClusterUndoStatus })),
        api.getObjectUndoStatus(get().apiBase).then((objectUndoStatus) => set({ objectUndoStatus }))
      ])
      set({ busy: false, busyMessage: undefined })
      if (hadGlobalHighlight) {
        await get().restoreGlobalClusterColors()
      }
      // F-03: check for persistent live session
      void get().checkLiveSession()
    } catch (error) {
      set({
        busy: false,
        busyMessage: undefined,
        error: error instanceof Error ? error.message : String(error)
      })
    }
  },

  setActiveViewMode(value) {
    set({ activeViewMode: value })
  },
  setFolderPath(value) {
    set({ folderPath: value })
  },
  setEmbeddingKey(value) {
    set({ embeddingKey: value })
  },
  setClusterKey(value) {
    set({
      clusterKey: value,
      dotplotResult: undefined,
      geneColorGene: undefined,
      colorMode: 'cluster',
      referenceClusters: [],
      sourceClusters: [],
      referencePropagationResult: undefined,
      markerDiscoveryTargets: [],
      markerDiscoveryResult: undefined,
      moveClusterPreview: undefined,
      moveClusterResult: undefined
    })
  },
  setMaxPoints(value) {
    set({ maxPoints: value })
  },
  setMinPerCluster(value) {
    set({ minPerCluster: value })
  },
  setMaxPerCluster(value) {
    set({ maxPerCluster: value })
  },
  setGlobalEmbeddingKey(value) {
    set({ globalEmbeddingKey: value })
  },
  setGlobalClusterKey(value) {
    set({ globalClusterKey: value })
  },
  setGlobalMaxPoints(value) {
    set({ globalMaxPoints: value })
  },
  setGlobalMinPerCluster(value) {
    set({ globalMinPerCluster: value })
  },
  setGlobalMaxPerCluster(value) {
    set({ globalMaxPerCluster: value })
  },
  setColorMode(value) {
    set({ colorMode: value })
  },
  setGlobalColorMode(value) {
    set({ globalColorMode: value })
  },
  setPropagationMethod(value) {
    set({ propagationMethod: value })
  },
  setPropagationScope(value) {
    set({ propagationScope: value })
  },
  setMinScore(value) {
    set({ minScore: value })
  },
  setMinMargin(value) {
    set({ minMargin: value })
  },
  setAnnotateAll(value) {
    set({ annotateAll: value })
  },
  setGraphSmoothing(value) {
    set({ graphSmoothing: value })
  },
  setPointSize(value) {
    set({ pointSize: value })
  },
  setPointOpacity(value) {
    set({ pointOpacity: value })
  },
  setPolygonStrokeWidth(value) {
    set({ polygonStrokeWidth: value })
  },
  setFlipHorizontal(value) {
    set({ flipHorizontal: value })
  },
  setFlipVertical(value) {
    set({ flipVertical: value })
  },
  setClusterVisibility(clusterId, visible) {
    set((state) => ({
      clusterVisibility: {
        ...state.clusterVisibility,
        [clusterId]: visible
      }
    }))
  },
  restoreClusterColorView() {
    if (get().activeViewMode === 'global') {
      void get().restoreGlobalClusterColors()
      return
    }
    set({ colorMode: 'cluster', geneColorGene: undefined })
  },
  async promoteReannotNewToCanonical() {
    const { selectedObjectId } = get()
    if (!selectedObjectId) {
      set({ error: 'Select an object first.' })
      return
    }
    set({ busy: true, error: undefined, promoteReannotResult: undefined })
    try {
      const result = await api.promoteReannotNew(get().apiBase, selectedObjectId)
      const metadata = await api.getMetadata(get().apiBase, selectedObjectId)
      set({
        metadata,
        clusterKey: 'reannot_label',
        promoteReannotResult: result,
        colorMode: 'cluster',
        busy: false
      })
      await get().loadObjectUndoStatus()
      await get().loadClusterLabelEditor()
      await get().refreshPointClusters('reannot_label')
    } catch (error) {
      set({ busy: false, error: error instanceof Error ? error.message : String(error) })
    }
  },
  toggleReferenceCluster(clusterId) {
    set((state) => ({
      referenceClusters: state.referenceClusters.includes(clusterId)
        ? state.referenceClusters.filter((value) => value !== clusterId)
        : [...state.referenceClusters, clusterId],
      sourceClusters: state.sourceClusters.filter((value) => value !== clusterId)
    }))
  },
  toggleSourceCluster(clusterId) {
    set((state) => ({
      sourceClusters: state.sourceClusters.includes(clusterId)
        ? state.sourceClusters.filter((value) => value !== clusterId)
        : [...state.sourceClusters, clusterId],
      referenceClusters: state.referenceClusters.filter((value) => value !== clusterId)
    }))
  },
  setReferencePropagationName(value) {
    set({ referencePropagationName: value })
  },
  setReferencePropagationNeighbors(value) {
    set({ referencePropagationNeighbors: value })
  },

  startDrawing() {
    set({ isDrawing: true, draftVertices: [], draftPolygonId: undefined, error: undefined })
  },
  stopDrawing() {
    set({ isDrawing: false, draftVertices: [], draftPolygonId: undefined })
  },
  addDraftVertex(vertex) {
    if (!get().isDrawing) {
      return
    }
    set((state) => ({ draftVertices: [...state.draftVertices, vertex] }))
  },
  updateDraftVertex(index, vertex) {
    set((state) => ({
      draftVertices: state.draftVertices.map((current, currentIndex) =>
        currentIndex === index ? vertex : current
      )
    }))
  },
  undoDraftVertex() {
    set((state) => ({ draftVertices: state.draftVertices.slice(0, -1) }))
  },
  async finalizeDraftPolygon() {
    const { selectedObjectId, embeddingKey, clusterKey, draftVertices, draftPolygonId } = get()
    if (draftVertices.length < 3) {
      set({ error: 'A polygon needs at least three points.' })
      return
    }
    if (!selectedObjectId || !embeddingKey || !clusterKey) {
      set({ error: 'Select an object, embedding key, and cluster key first.' })
      return
    }

    const polygonId = randomPolygonId()
    const vertices = [...draftVertices, draftVertices[0]]
    const effectivePolygonId = draftPolygonId ?? polygonId
    set({ busy: true, busyMessage: draftPolygonId ? 'Updating polygon' : 'Closing polygon', error: undefined })
    try {
      const selection = await api.polygonSelect(get().apiBase, selectedObjectId, {
        embedding_key: embeddingKey,
        cluster_key: clusterKey,
        polygons: [{ polygon_id: effectivePolygonId, vertices }]
      })
      const summary = selection.polygon_summaries[0]
      const dominantCluster = summary?.clusters[0]?.cluster ?? ''
      const polygon: PolygonRecord = {
        id: effectivePolygonId,
        vertices,
        clusterId:
          get().polygons.find((entry) => entry.id === effectivePolygonId)?.clusterId ?? dominantCluster,
        clusterName:
          get().polygons.find((entry) => entry.id === effectivePolygonId)?.clusterName ?? '',
        includeForPropagation: true,
        nCells: summary?.n_cells ?? 0,
        clusterSummary: summary?.clusters ?? []
      }
      set((state) => {
        const existingIndex = state.polygons.findIndex((entry) => entry.id === effectivePolygonId)
        const polygons =
          existingIndex >= 0
            ? state.polygons.map((entry) => (entry.id === effectivePolygonId ? { ...entry, ...polygon } : entry))
            : [...state.polygons, polygon]
        return {
          polygons,
          draftVertices: [],
          draftPolygonId: undefined,
          isDrawing: false,
          busy: false,
          busyMessage: undefined
        }
      })
    } catch (error) {
      set({
        busy: false,
        busyMessage: undefined,
        error: error instanceof Error ? error.message : String(error)
      })
    }
  },
  clearDraftPolygon() {
    set({ draftVertices: [], draftPolygonId: undefined, isDrawing: false })
  },
  editPolygonVertices(polygonId) {
    const polygon = get().polygons.find((entry) => entry.id === polygonId)
    if (!polygon) {
      return
    }
    const openVertices =
      polygon.vertices.length > 1 &&
      polygon.vertices[0][0] === polygon.vertices[polygon.vertices.length - 1][0] &&
      polygon.vertices[0][1] === polygon.vertices[polygon.vertices.length - 1][1]
        ? polygon.vertices.slice(0, -1)
        : polygon.vertices
    set({
      isDrawing: true,
      draftPolygonId: polygonId,
      draftVertices: openVertices.map((vertex) => [...vertex]),
      error: undefined
    })
  },
  updatePolygon(polygonId, updates) {
    set((state) => ({
      polygons: state.polygons.map((polygon) =>
        polygon.id === polygonId ? { ...polygon, ...updates } : polygon
      )
    }))
  },
  removePolygon(polygonId) {
    set((state) => ({
      polygons: state.polygons.filter((polygon) => polygon.id !== polygonId)
    }))
  },
  clearPolygons() {
    set({ polygons: [], draftVertices: [], isDrawing: false })
  },

  async loadUmap(overrides) {
    const {
      selectedObjectId,
      embeddingKey,
      clusterKey,
      maxPoints,
      minPerCluster,
      maxPerCluster,
      colorMode,
      geneColorGene
    } =
      get()
    const nextEmbeddingKey = overrides?.embeddingKey ?? embeddingKey
    const nextClusterKey = overrides?.clusterKey ?? clusterKey
    const nextGeneName =
      overrides?.geneName !== undefined ? overrides.geneName : colorMode === 'gene' ? geneColorGene ?? null : null
    if (!selectedObjectId || !nextEmbeddingKey) {
      return
    }
    set({ busy: true, busyMessage: 'Loading lineage UMAP', error: undefined })
    try {
      const response = await api.getUmap(get().apiBase, selectedObjectId, {
        embedding_key: nextEmbeddingKey,
        cluster_key: nextClusterKey || null,
        gene_name: nextGeneName,
        max_points: maxPoints,
        min_per_cluster: minPerCluster,
        max_per_cluster: maxPerCluster,
        random_seed: 13
      })
      set({ points: response.points, viewToken: response.view_token ?? null, busy: false, busyMessage: undefined })
    } catch (error) {
      set({
        busy: false,
        busyMessage: undefined,
        error: error instanceof Error ? error.message : String(error)
      })
    }
  },

  async loadGlobalUmap(overrides) {
    const {
      globalEmbeddingKey,
      globalClusterKey,
      globalMaxPoints,
      globalMinPerCluster,
      globalMaxPerCluster,
      globalColorMode,
      globalGeneColorGene
    } = get()
    const nextEmbeddingKey = overrides?.embeddingKey ?? globalEmbeddingKey
    const nextClusterKey = overrides?.clusterKey ?? globalClusterKey
    if (!nextEmbeddingKey) {
      return
    }
    set({ busy: true, busyMessage: 'Loading global UMAP', error: undefined })
    try {
      // Combined view: each lineage object contributes its own sampled subset,
      // matched back into the global embedding — rather than an independent
      // sample drawn straight from the global object.
      const response = await api.getGlobalUmapCombined(get().apiBase, {
        embedding_key: nextEmbeddingKey,
        cluster_key: nextClusterKey || null,
        max_points: globalMaxPoints,
        min_per_cluster: globalMinPerCluster,
        max_per_cluster: globalMaxPerCluster,
        random_seed: 13
      })
      set({
        globalPoints: response.points,
        globalBasePoints: response.points,
        globalViewToken: response.view_token ?? null,
        globalHighlight: undefined,
        busy: false,
        busyMessage: undefined
      })
      if (globalColorMode === 'gene' && globalGeneColorGene) {
        await get().colorBySelectedGene()
      }
    } catch (error) {
      set({
        busy: false,
        busyMessage: undefined,
        error: error instanceof Error ? error.message : String(error)
      })
    }
  },

  async refreshGlobalPointClusters(nextClusterKey) {
    const { globalClusterKey, globalPoints, globalBasePoints, globalHighlight } = get()
    const effectiveClusterKey = nextClusterKey ?? globalClusterKey
    if (!effectiveClusterKey || (globalPoints.length === 0 && globalBasePoints.length === 0)) {
      return
    }
    set({ busy: true, busyMessage: 'Refreshing global cluster colors', error: undefined })
    try {
      const basePoints = globalBasePoints.length > 0 ? globalBasePoints : globalPoints
      const baseResponse = await api.getGlobalPointClusters(get().apiBase, {
        cluster_key: effectiveClusterKey,
        indices: basePoints.map((point) => point.index)
      })
      const baseClusterMap = new Map(baseResponse.values.map((row) => [row.index, row.cluster] as const))

      let currentClusterMap = baseClusterMap
      if (globalHighlight && !samePointSequence(globalPoints, basePoints)) {
        const currentResponse = await api.getGlobalPointClusters(get().apiBase, {
          cluster_key: effectiveClusterKey,
          indices: globalPoints.map((point) => point.index)
        })
        currentClusterMap = new Map(currentResponse.values.map((row) => [row.index, row.cluster] as const))
      }

      set((state) => ({
        globalBasePoints: basePoints.map((point) => ({
          ...point,
          cluster: baseClusterMap.get(point.index) ?? point.cluster
        })),
        globalPoints: state.globalPoints.map((point) => ({
          ...point,
          cluster: currentClusterMap.get(point.index) ?? point.cluster
        })),
        busy: false,
        busyMessage: undefined
      }))
    } catch (error) {
      set({
        busy: false,
        busyMessage: undefined,
        error: error instanceof Error ? error.message : String(error)
      })
    }
  },

  async highlightClusterInGlobal(clusterId, clusterName) {
    const { selectedObjectId, clusterKey, globalBasePoints, globalPoints } = get()
    const basePoints = globalBasePoints.length > 0 ? globalBasePoints : globalPoints
    if (!selectedObjectId || !clusterKey || basePoints.length === 0) {
      set({ error: 'Load both the lineage object and the global object first.' })
      return
    }
    set({ busy: true, busyMessage: 'Highlighting visible global sample', error: undefined })
    try {
      const response: VisibleHighlightResponse = await api.highlightVisibleGlobalFromObject(get().apiBase, {
        source_object_id: selectedObjectId,
        source_cluster_key: clusterKey,
        source_cluster_id: clusterId,
        indices: basePoints.map((point) => point.index)
      })
      const highlightMap = new Map(response.values.map((row) => [row.index, row.is_highlighted] as const))
      const highlightedPoints = basePoints.map((point) => ({
        ...point,
        is_highlighted: highlightMap.get(point.index) ?? false
      }))
      set({
        globalPoints: highlightedPoints,
        globalHighlight: {
          sourceObjectId: selectedObjectId,
          sourceClusterKey: clusterKey,
          sourceClusterId: clusterId,
          sourceClusterName: clusterName,
          highlightedTotal: response.highlighted_total ?? 0,
          highlightedDisplayed: response.highlighted_displayed ?? 0
        },
        globalColorMode: 'cluster',
        globalGeneColorGene: undefined,
        activeViewMode: 'global',
        busy: false,
        busyMessage: undefined
      })
    } catch (error) {
      set({
        busy: false,
        busyMessage: undefined,
        error: error instanceof Error ? error.message : String(error)
      })
    }
  },

  async restoreGlobalClusterColors() {
    const { globalHighlight, globalBasePoints } = get()
    set({
      globalPoints: globalBasePoints,
      globalHighlight: undefined,
      globalColorMode: 'cluster',
      globalGeneColorGene: undefined
    })
  },

  async previewMoveCluster(clusterId, destinationObjectId) {
    const { selectedObjectId, clusterKey } = get()
    if (!selectedObjectId || !clusterKey || !destinationObjectId) {
      set({ moveClusterPreview: undefined })
      return
    }
    set({ busy: true, busyMessage: 'Previewing move', error: undefined, moveClusterPreview: undefined })
    try {
      const preview = await api.previewMoveCluster(get().apiBase, selectedObjectId, {
        destination_object_id: destinationObjectId,
        cluster_key: clusterKey,
        cluster_id: clusterId
      })
      set({ moveClusterPreview: preview, busy: false, busyMessage: undefined })
    } catch (error) {
      set({
        busy: false,
        busyMessage: undefined,
        moveClusterPreview: undefined,
        error: error instanceof Error ? error.message : String(error)
      })
    }
  },

  clearMoveClusterPreview() {
    set({ moveClusterPreview: undefined })
  },

  async moveClusterToObject(clusterId, destinationObjectId) {
    const { selectedObjectId, clusterKey } = get()
    if (!selectedObjectId || !clusterKey) {
      set({ error: 'Select an object and cluster key first.' })
      return
    }
    if (!destinationObjectId) {
      set({ error: 'Select a destination object first.' })
      return
    }
    set({ busy: true, busyMessage: 'Moving cluster', error: undefined, moveClusterResult: undefined })
    try {
      const result = await api.moveCluster(get().apiBase, selectedObjectId, {
        destination_object_id: destinationObjectId,
        cluster_key: clusterKey,
        cluster_id: clusterId,
        allow_overwrite: true
      })
      const objects = await api.scanFolder(get().apiBase, get().folderPath)
      await get().selectObject(selectedObjectId)
      const undoStatus = await api.getMoveClusterUndoStatus(get().apiBase)
      set({
        objects,
        moveClusterPreview: undefined,
        moveClusterResult: result,
        moveClusterUndoStatus: undoStatus,
        moveClusterUndoResult: undefined,
        objectUndoResult: undefined,
        busy: false,
        busyMessage: undefined
      })
      if (get().globalHighlight?.sourceClusterId === clusterId) {
        await get().restoreGlobalClusterColors()
      }
    } catch (error) {
      set({
        busy: false,
        busyMessage: undefined,
        error: error instanceof Error ? error.message : String(error)
      })
    }
  },

  async loadMoveClusterUndoStatus() {
    try {
      const status = await api.getMoveClusterUndoStatus(get().apiBase)
      set({ moveClusterUndoStatus: status })
    } catch (error) {
      set({
        moveClusterUndoStatus: undefined,
        error: error instanceof Error ? error.message : String(error)
      })
    }
  },

  async undoLatestMoveCluster() {
    const { selectedObjectId } = get()
    set({
      busy: true,
      busyMessage: 'Undoing latest move',
      error: undefined,
      moveClusterResult: undefined,
      moveClusterUndoResult: undefined
    })
    try {
      const result = await api.undoMoveCluster(get().apiBase)
      const objects = await api.scanFolder(get().apiBase, get().folderPath)
      const nextSelectedObjectId =
        objects.find((object) => object.object_id === selectedObjectId)?.object_id ??
        objects.find((object) => object.is_valid)?.object_id ??
        ''
      if (nextSelectedObjectId) {
        await get().selectObject(nextSelectedObjectId)
      }
      const undoStatus = await api.getMoveClusterUndoStatus(get().apiBase)
      set({
        objects,
        moveClusterUndoStatus: undoStatus,
        moveClusterUndoResult: result,
        busy: false,
        busyMessage: undefined
      })
      if (get().globalHighlight) {
        await get().restoreGlobalClusterColors()
      }
    } catch (error) {
      set({
        busy: false,
        busyMessage: undefined,
        error: error instanceof Error ? error.message : String(error)
      })
    }
  },

  async loadObjectUndoStatus() {
    try {
      const status = await api.getObjectUndoStatus(get().apiBase)
      set({ objectUndoStatus: status })
    } catch (error) {
      set({
        objectUndoStatus: undefined,
        error: error instanceof Error ? error.message : String(error)
      })
    }
  },

  async undoLatestObjectChange() {
    const { selectedObjectId } = get()
    set({
      busy: true,
      busyMessage: 'Undoing latest object change',
      error: undefined,
      objectUndoResult: undefined,
      moveClusterUndoResult: undefined
    })
    try {
      const result = await api.undoObjectChange(get().apiBase)
      const objects = await api.scanFolder(get().apiBase, get().folderPath)
      const nextSelectedObjectId =
        objects.find((object) => object.object_id === selectedObjectId)?.object_id ??
        objects.find((object) => object.is_valid)?.object_id ??
        ''
      if (nextSelectedObjectId) {
        await get().selectObject(nextSelectedObjectId)
      }
      const [objectUndoStatus, moveClusterUndoStatus] = await Promise.all([
        api.getObjectUndoStatus(get().apiBase),
        api.getMoveClusterUndoStatus(get().apiBase)
      ])
      set({
        objects,
        objectUndoStatus,
        objectUndoResult: result,
        moveClusterUndoStatus,
        busy: false,
        busyMessage: undefined
      })
      if (get().globalHighlight) {
        await get().restoreGlobalClusterColors()
      }
    } catch (error) {
      set({
        busy: false,
        busyMessage: undefined,
        error: error instanceof Error ? error.message : String(error)
      })
    }
  },

  async refreshPointClusters(nextClusterKey) {
    const { selectedObjectId, clusterKey, points } = get()
    const effectiveClusterKey = nextClusterKey ?? clusterKey
    if (!selectedObjectId || !effectiveClusterKey || points.length === 0) {
      return
    }
    set({ busy: true, busyMessage: 'Refreshing cluster colors', error: undefined })
    try {
      const response = await api.getPointClusters(get().apiBase, selectedObjectId, {
        cluster_key: effectiveClusterKey,
        indices: points.map((point) => point.index)
      })
      const clusterMap = new Map(response.values.map((row) => [row.index, row.cluster] as const))
      set((state) => ({
        points: state.points.map((point) => ({
          ...point,
          cluster: clusterMap.get(point.index) ?? point.cluster
        })),
        busy: false,
        busyMessage: undefined
      }))
    } catch (error) {
      set({
        busy: false,
        busyMessage: undefined,
        error: error instanceof Error ? error.message : String(error)
      })
    }
  },

  async loadClusterLabelEditor() {
    const { selectedObjectId, clusterKey, clusterVisibility } = get()
    if (!selectedObjectId || !clusterKey) {
      set({ clusterLabelEditor: undefined, clusterVisibility: {} })
      return
    }
    try {
      const editor = await api.getClusterLabelEditor(get().apiBase, selectedObjectId, clusterKey)
      const nextVisibility = Object.fromEntries(
        editor.rows.map((row) => [row.cluster_id, clusterVisibility[row.cluster_id] ?? true])
      )
      set({
        clusterLabelEditor: editor,
        clusterLabelSaveResult: undefined,
        clusterVisibility: nextVisibility
      })
    } catch (error) {
      set({
        clusterLabelEditor: undefined,
        clusterVisibility: {},
        error: error instanceof Error ? error.message : String(error)
      })
    }
  },

  updateClusterLabelName(clusterId, displayName) {
    set((state) => ({
      clusterLabelEditor: state.clusterLabelEditor
        ? {
            ...state.clusterLabelEditor,
            rows: state.clusterLabelEditor.rows.map((row) =>
              row.cluster_id === clusterId ? { ...row, display_name: displayName } : row
            )
          }
        : undefined
    }))
  },

  async saveClusterLabelEditor() {
    const { selectedObjectId, clusterLabelEditor, clusterKey, metadata } = get()
    if (!selectedObjectId || !clusterLabelEditor || !clusterKey) {
      return
    }
    const mapping = Object.fromEntries(
      clusterLabelEditor.rows
        .map((row) => [row.cluster_id, (row.display_name ?? '').trim()] as const)
        .filter(([, displayName]) => displayName.length > 0)
    )
    set({
      busy: true,
      busyMessage: 'Saving cluster names',
      trackedTask: {
        label: 'Saving cluster names',
        startedAt: Date.now(),
        estimatedMs: estimateClusterSaveMs(metadata?.shape[0] ?? 50000)
      },
      error: undefined,
      clusterLabelSaveResult: undefined
    })
    try {
      const result = await api.saveClusterLabelEditor(get().apiBase, selectedObjectId, {
        cluster_key: clusterKey,
        display_column: clusterLabelEditor.display_column,
        mapping
      })
      const nextMetadata = await api.getMetadata(get().apiBase, selectedObjectId)
      set({
        metadata: nextMetadata,
        clusterLabelSaveResult: result,
        busy: false,
        busyMessage: undefined,
        trackedTask: undefined
      })
      await get().loadObjectUndoStatus()
      await get().loadClusterLabelEditor()
      await get().loadUmap({ clusterKey: get().clusterKey })
    } catch (error) {
      set({
        busy: false,
        busyMessage: undefined,
        trackedTask: undefined,
        error: error instanceof Error ? error.message : String(error)
      })
    }
  },

  async runReferencePropagation() {
    const {
      selectedObjectId,
      clusterKey,
      referenceClusters,
      sourceClusters,
      referencePropagationName,
      referencePropagationNeighbors
    } = get()
    if (!selectedObjectId || !clusterKey) {
      set({ error: 'Select an object and cluster key first.' })
      return
    }
    if (referenceClusters.length === 0 || sourceClusters.length === 0) {
      set({ error: 'Select at least one reference cluster and one source cluster.' })
      return
    }
    set({ busy: true, busyMessage: 'Running reference propagation', error: undefined, referencePropagationResult: undefined })
    try {
      const result = await api.referencePropagate(get().apiBase, selectedObjectId, {
        cluster_key: clusterKey,
        reference_clusters: referenceClusters,
        source_clusters: sourceClusters,
        output_name: referencePropagationName.trim() || 'new',
        n_neighbors: referencePropagationNeighbors
      })
      await get().selectObject(selectedObjectId)
      set({
        clusterKey: result.new_cluster_key,
        colorMode: 'cluster',
        referencePropagationResult: result,
        referenceClusters: [],
        sourceClusters: [],
        markerDiscoveryTargets: [],
        markerDiscoveryResult: undefined
      })
      await get().loadClusterLabelEditor()
      await get().loadUmap({ clusterKey: result.new_cluster_key, geneName: null })
    } catch (error) {
      set({
        busy: false,
        busyMessage: undefined,
        error: error instanceof Error ? error.message : String(error)
      })
    }
  },

  async loadGenes() {
    const { selectedObjectId } = get()
    if (!selectedObjectId) {
      set({ geneCatalog: undefined, selectedGenes: [], dotplotResult: undefined })
      return
    }
    try {
      const geneCatalog = await api.getGenes(get().apiBase, selectedObjectId)
      set((state) => ({
        geneCatalog,
        selectedGenes: state.selectedGenes.filter((gene) => geneCatalog.genes.includes(gene)),
        activeHighlightedGene: effectiveHighlightedGene(
          state.selectedGenes.filter((gene) => geneCatalog.genes.includes(gene)),
          state.activeHighlightedGene
        ),
        dotplotResult: undefined
      }))
    } catch (error) {
      set({
        geneCatalog: undefined,
        error: error instanceof Error ? error.message : String(error)
      })
    }
  },

  async loadGlobalGenes() {
    try {
      const globalGeneCatalog = await api.getGlobalGenes(get().apiBase)
      set((state) => ({
        globalGeneCatalog,
        selectedGenes: state.selectedGenes.filter((gene) => globalGeneCatalog.genes.includes(gene)),
        activeHighlightedGene: effectiveHighlightedGene(
          state.selectedGenes.filter((gene) => globalGeneCatalog.genes.includes(gene)),
          state.activeHighlightedGene
        ),
        dotplotResult: undefined
      }))
    } catch (error) {
      set({
        globalGeneCatalog: undefined,
        error: error instanceof Error ? error.message : String(error)
      })
    }
  },

  setGeneSearch(value) {
    set({ geneSearch: value })
  },
  addSelectedGenes(genes) {
    set((state) => {
      const merged = [...state.selectedGenes]
      for (const gene of genes) {
        if (!merged.includes(gene)) {
          merged.push(gene)
        }
      }
      return {
        selectedGenes: merged,
        activeHighlightedGene: effectiveHighlightedGene(merged, state.activeHighlightedGene),
        dotplotResult: undefined
      }
    })
  },
  toggleGeneSelected(gene) {
    set((state) => {
      const selected = state.selectedGenes.includes(gene)
        ? state.selectedGenes.filter((value) => value !== gene)
        : [...state.selectedGenes, gene]
      return {
        selectedGenes: selected,
        activeHighlightedGene: effectiveHighlightedGene(selected, state.activeHighlightedGene),
        dotplotResult: undefined
      }
    })
  },
  clearSelectedGenes() {
    set({ selectedGenes: [], activeHighlightedGene: undefined, dotplotResult: undefined })
  },
  setActiveHighlightedGene(gene) {
    set((state) => ({
      activeHighlightedGene:
        gene && state.selectedGenes.includes(gene) ? gene : effectiveHighlightedGene(state.selectedGenes, undefined),
      dotplotResult: undefined
    }))
  },
  toggleFavoriteGene(gene) {
    set((state) => {
      const favoriteGenes = state.favoriteGenes.includes(gene)
        ? state.favoriteGenes.filter((value) => value !== gene)
        : [gene, ...state.favoriteGenes]
      saveFavoriteGenes(favoriteGenes)
      return { favoriteGenes }
    })
  },
  reorderSelectedGenes(fromIndex, toIndex) {
    set((state) => {
      if (
        fromIndex < 0 ||
        toIndex < 0 ||
        fromIndex >= state.selectedGenes.length ||
        toIndex >= state.selectedGenes.length ||
        fromIndex === toIndex
      ) {
        return state
      }
      const selectedGenes = moveArrayItem(state.selectedGenes, fromIndex, toIndex)
      return {
        selectedGenes,
        activeHighlightedGene: effectiveHighlightedGene(selectedGenes, state.activeHighlightedGene),
        dotplotResult: undefined
      }
    })
  },
  toggleMarkerDiscoveryTarget(clusterId) {
    set((state) => ({
      markerDiscoveryTargets: state.markerDiscoveryTargets.includes(clusterId)
        ? state.markerDiscoveryTargets.filter((value) => value !== clusterId)
        : [...state.markerDiscoveryTargets, clusterId]
    }))
  },
  setMarkerDiscoveryTopN(value) {
    set({ markerDiscoveryTopN: value })
  },
  async discoverMarkers() {
    const { selectedObjectId, clusterKey, clusterLabelEditor, clusterVisibility, markerDiscoveryTargets, markerDiscoveryTopN } =
      get()
    if (!selectedObjectId || !clusterKey || !clusterLabelEditor) {
      set({ error: 'Select an object and cluster key first.' })
      return
    }
    const activeClusters = clusterLabelEditor.rows
      .map((row) => row.cluster_id)
      .filter((clusterId) => clusterVisibility[clusterId] ?? true)
    if (activeClusters.length === 0) {
      set({ error: 'At least one checked cluster is required for marker discovery.' })
      return
    }
    if (markerDiscoveryTargets.length === 0) {
      set({ error: 'Select at least one target cluster for marker discovery.' })
      return
    }
    set({ busy: true, busyMessage: 'Discovering markers', error: undefined, markerDiscoveryResult: undefined })
    try {
      const result = await api.discoverMarkers(get().apiBase, selectedObjectId, {
        cluster_key: clusterKey,
        active_clusters: activeClusters,
        target_clusters: markerDiscoveryTargets,
        top_n: markerDiscoveryTopN
      })
      set((state) => ({
        markerDiscoveryResult: result,
        selectedGenes: [...state.selectedGenes, ...result.candidate_genes.filter((gene) => !state.selectedGenes.includes(gene))],
        activeHighlightedGene: effectiveHighlightedGene(
          [...state.selectedGenes, ...result.candidate_genes.filter((gene) => !state.selectedGenes.includes(gene))],
          state.activeHighlightedGene
        ),
        busy: false,
        busyMessage: undefined
      }))
    } catch (error) {
      set({
        busy: false,
        busyMessage: undefined,
        error: error instanceof Error ? error.message : String(error)
      })
    }
  },
  async colorBySelectedGene() {
    const {
      selectedGenes,
      activeHighlightedGene,
      selectedObjectId,
      points,
      viewToken,
      geneColorGene,
      colorMode,
      activeViewMode,
      globalBasePoints,
      globalPoints,
      globalViewToken,
      globalGeneColorGene,
      globalColorMode,
      geneCatalog,
      globalGeneCatalog
    } = get()
    const gene = effectiveHighlightedGene(selectedGenes, activeHighlightedGene)
    if (!gene) {
      set({ error: 'Select one checked gene to color the UMAP by expression.' })
      return
    }
    const availableGenes = activeViewMode === 'global' ? globalGeneCatalog?.genes ?? [] : geneCatalog?.genes ?? []
    if (!availableGenes.includes(gene)) {
      set({ error: `Gene is not available in the current ${activeViewMode} view: ${gene}` })
      return
    }
    if (activeViewMode === 'lineage' && !selectedObjectId) {
      set({ error: 'Select an object first.' })
      return
    }
    if (
      activeViewMode === 'lineage' &&
      colorMode === 'gene' &&
      geneColorGene === gene &&
      points.every((point) => point.gene_expression != null)
    ) {
      set({ colorMode: 'gene' })
      return
    }
    if (
      activeViewMode === 'global' &&
      globalColorMode === 'gene' &&
      globalGeneColorGene === gene &&
      globalBasePoints.every((point) => point.gene_expression != null)
    ) {
      set({ globalColorMode: 'gene' })
      return
    }
    const displayedCount = activeViewMode === 'global' ? (globalBasePoints.length || globalPoints.length) : points.length
    set({
      busy: true,
      busyMessage: 'Loading gene colors',
      trackedTask: {
        label: `Coloring by ${gene}`,
        startedAt: Date.now(),
        estimatedMs: estimateGeneColorMs(displayedCount || 50000)
      },
      error: undefined
    })
    try {
      if (activeViewMode === 'global') {
        const basePoints = globalBasePoints.length > 0 ? globalBasePoints : globalPoints
        const response = await api.getGlobalGeneExpression(get().apiBase, {
          gene_name: gene,
          view_token: globalViewToken ?? undefined,
          indices: globalViewToken ? undefined : basePoints.map((point) => point.index)
        })
        const nextPoints = response.ordered_values
          ? basePoints.map((point, i) => ({ ...point, gene_expression: response.ordered_values![i] ?? 0, is_highlighted: undefined }))
          : (() => {
              const expressionMap = new Map(response.values.map((row) => [row.index, row.value] as const))
              return basePoints.map((point) => ({ ...point, gene_expression: expressionMap.get(point.index) ?? 0, is_highlighted: undefined }))
            })()
        set({
          globalBasePoints: nextPoints,
          globalPoints: nextPoints,
          globalHighlight: undefined,
          globalColorMode: 'gene',
          globalGeneColorGene: gene,
          busy: false,
          busyMessage: undefined,
          trackedTask: undefined
        })
      } else {
        const response = await api.getGeneExpression(get().apiBase, selectedObjectId, {
          gene_name: gene,
          view_token: viewToken ?? undefined,
          indices: viewToken ? undefined : points.map((point) => point.index)
        })
        if (response.ordered_values) {
          const orderedValues = response.ordered_values
          set((state) => ({
            points: state.points.map((point, i) => ({ ...point, gene_expression: orderedValues[i] ?? 0 })),
            colorMode: 'gene',
            geneColorGene: gene,
            busy: false,
            busyMessage: undefined,
            trackedTask: undefined
          }))
        } else {
          const expressionMap = new Map(response.values.map((row) => [row.index, row.value] as const))
          set((state) => ({
            points: state.points.map((point) => ({ ...point, gene_expression: expressionMap.get(point.index) ?? 0 })),
            colorMode: 'gene',
            geneColorGene: gene,
            busy: false,
            busyMessage: undefined,
            trackedTask: undefined
          }))
        }
      }
    } catch (error) {
      set({
        busy: false,
        busyMessage: undefined,
        trackedTask: undefined,
        error: error instanceof Error ? error.message : String(error)
      })
    }
  },
  async previewDotplot() {
    const { selectedObjectId, clusterKey, selectedGenes, activeViewMode, globalClusterKey } = get()
    if (activeViewMode === 'lineage' && (!selectedObjectId || !clusterKey)) {
      set({ error: 'Select an object and cluster key first.' })
      return
    }
    if (activeViewMode === 'global' && !globalClusterKey) {
      set({ error: 'Select a global cluster key first.' })
      return
    }
    if (selectedGenes.length === 0) {
      set({ error: 'Check at least one gene for the dotplot.' })
      return
    }
    set({ busy: true, busyMessage: 'Rendering dotplot', error: undefined })
    try {
      const dotplotResult =
        activeViewMode === 'global'
          ? await api.getGlobalMarkerDotplot(get().apiBase, {
              cluster_key: globalClusterKey,
              genes: selectedGenes,
              save_to_object_dir: false
            })
          : await api.getMarkerDotplot(get().apiBase, selectedObjectId, {
              cluster_key: clusterKey,
              genes: selectedGenes,
              save_to_object_dir: false
            })
      set({ dotplotResult, busy: false, busyMessage: undefined })
    } catch (error) {
      set({
        busy: false,
        busyMessage: undefined,
        error: error instanceof Error ? error.message : String(error)
      })
    }
  },
  async saveDotplot() {
    const { selectedObjectId, clusterKey, selectedGenes, activeViewMode, globalClusterKey } = get()
    if (activeViewMode === 'lineage' && (!selectedObjectId || !clusterKey)) {
      set({ error: 'Select an object and cluster key first.' })
      return
    }
    if (activeViewMode === 'global' && !globalClusterKey) {
      set({ error: 'Select a global cluster key first.' })
      return
    }
    if (selectedGenes.length === 0) {
      set({ error: 'Check at least one gene for the dotplot.' })
      return
    }
    set({ busy: true, busyMessage: 'Saving dotplot', error: undefined })
    try {
      const dotplotResult =
        activeViewMode === 'global'
          ? await api.getGlobalMarkerDotplot(get().apiBase, {
              cluster_key: globalClusterKey,
              genes: selectedGenes,
              save_to_object_dir: true
            })
          : await api.getMarkerDotplot(get().apiBase, selectedObjectId, {
              cluster_key: clusterKey,
              genes: selectedGenes,
              save_to_object_dir: true
            })
      set({ dotplotResult, busy: false, busyMessage: undefined })
    } catch (error) {
      set({
        busy: false,
        busyMessage: undefined,
        error: error instanceof Error ? error.message : String(error)
      })
    }
  },

  async propagate() {
    const {
      selectedObjectId,
      embeddingKey,
      clusterKey,
      polygons,
      propagationMethod,
      propagationScope,
      minScore,
      minMargin,
      annotateAll,
      graphSmoothing,
      metadata
    } = get()

    if (!selectedObjectId || !embeddingKey || !clusterKey) {
      set({ error: 'Select an object, embedding key, and cluster key first.' })
      return
    }

    const activePolygons = polygons.filter(
      (polygon) => polygon.includeForPropagation && polygon.vertices.length >= 3 && polygon.clusterId.trim()
    )
    if (activePolygons.length === 0) {
      set({ error: 'Tick at least one polygon and give it a cluster ID before propagating.' })
      return
    }

    const sessionId = randomSessionId()
    set({
      busy: true,
      busyMessage: 'Propagating labels',
      trackedTask: {
        label: 'Propagating labels',
        startedAt: Date.now(),
        estimatedMs: estimatePropagateMs(metadata?.shape[0] ?? 50000, propagationMethod)
      },
      error: undefined,
      sessionId,
      savePromptOpen: false,
      saveResult: undefined,
      propagationResult: undefined
    })
    try {
      let sessionSummary: SessionSummary | undefined
      for (const polygon of activePolygons) {
        sessionSummary = await api.seedLabels(get().apiBase, selectedObjectId, {
          session_id: sessionId,
          embedding_key: embeddingKey,
          cluster_key: clusterKey,
          label: polygon.clusterId.trim(),
          display_name: polygon.clusterName.trim() || polygon.clusterId.trim(),
          notes: null,
          polygons: [{ polygon_id: polygon.id, vertices: polygon.vertices }]
        })
      }

      const propagationResult = await api.propagate(get().apiBase, selectedObjectId, {
        session_id: sessionId,
        embedding_key: embeddingKey,
        cluster_key: clusterKey,
        method: propagationMethod,
        scope: propagationScope,
        min_score: minScore,
        min_margin: minMargin,
        annotate_all: annotateAll,
        graph_smoothing: graphSmoothing,
        n_neighbors: 15,
        neighborhood_hops: 2
      })

      set({
        sessionSummary,
        propagationResult,
        colorMode: 'annotation',
        savePromptOpen: true,
        busy: false,
        busyMessage: undefined,
        trackedTask: undefined
      })
    } catch (error) {
      set({
        busy: false,
        busyMessage: undefined,
        trackedTask: undefined,
        error: error instanceof Error ? error.message : String(error)
      })
    }
  },

  async refreshSessionSummary() {
    const { selectedObjectId, sessionId } = get()
    if (!selectedObjectId) {
      return
    }
    try {
      const sessionSummary = await api.sessionSummary(get().apiBase, selectedObjectId, sessionId)
      set({ sessionSummary })
    } catch {
      // Ignore empty sessions.
    }
  },

  async saveSession() {
    const { selectedObjectId, sessionId, propagationResult, sessionSummary, metadata } = get()
    // propagationResult is only set by a propagate() call made in this browser
    // session; a session restored after a backend restart only has
    // sessionSummary.last_propagation. The backend is the real source of
    // truth (the /save endpoint itself checks for a computed result) — this
    // is just a friendly pre-check, so it must accept either.
    if (!selectedObjectId || !(propagationResult || sessionSummary?.last_propagation)) {
      set({ error: 'Run propagation before saving.' })
      return
    }
    set({
      busy: true,
      busyMessage: 'Saving reannotated object',
      trackedTask: {
        label: 'Saving reannotated object',
        startedAt: Date.now(),
        estimatedMs: estimateClusterSaveMs(metadata?.shape[0] ?? 50000)
      },
      error: undefined
    })
    try {
      const saveResult = await api.save(get().apiBase, selectedObjectId, { session_id: sessionId })
      set({ saveResult, savePromptOpen: false, busy: false, busyMessage: undefined, trackedTask: undefined })
      await get().loadObjectUndoStatus()
    } catch (error) {
      set({
        busy: false,
        busyMessage: undefined,
        trackedTask: undefined,
        error: error instanceof Error ? error.message : String(error)
      })
    }
  },

  dismissSavePrompt() {
    set({ savePromptOpen: false })
  },

  async resetPropagation() {
    const { selectedObjectId, sessionId } = get()
    if (selectedObjectId) {
      try {
        await api.clearSession(get().apiBase, selectedObjectId, sessionId)
      } catch {
        // Session may not exist yet.
      }
    }
    set({
      sessionId: randomSessionId(),
      sessionSummary: undefined,
      propagationResult: undefined,
      saveResult: undefined,
      savePromptOpen: false,
      colorMode: 'cluster',
      error: undefined
    })
  },

  async resetSession() {
    const { selectedObjectId, sessionId } = get()
    if (selectedObjectId) {
      try {
        await api.clearSession(get().apiBase, selectedObjectId, sessionId)
      } catch {
        // Session may not exist yet.
      }
    }
    set({
      polygons: [],
      draftVertices: [],
      draftPolygonId: undefined,
      isDrawing: false,
      sessionId: randomSessionId(),
      sessionSummary: undefined,
      propagationResult: undefined,
      saveResult: undefined,
      savePromptOpen: false,
      colorMode: 'cluster',
      error: undefined
    })
  },
  stopCurrentTask() {
    abortActiveRequests()
    set({
      busy: false,
      busyMessage: undefined,
      trackedTask: undefined,
      error: 'Stopped current request.'
    })
  },

  // F-04/F-13 — Obs metadata coloring
  async loadObsColumns() {
    const { selectedObjectId, activeViewMode, apiBase } = get()
    if (activeViewMode !== 'global' && !selectedObjectId) return
    try {
      const response = activeViewMode === 'global'
        ? await api.getGlobalObsColumns(apiBase)
        : await api.getObsColumns(apiBase, selectedObjectId)
      set({ obsColumns: response.columns })
    } catch (error) {
      set({ obsColumns: [], error: error instanceof Error ? error.message : String(error) })
    }
  },
  async setActiveObsColumn(column) {
    const { selectedObjectId, activeViewMode, apiBase, points, globalPoints } = get()
    set({ activeObsColumn: column })
    if (!column) {
      set({ obsColorValues: {} })
      return
    }
    const displayedPoints = activeViewMode === 'global' ? globalPoints : points
    const indices = displayedPoints.map((p) => p.index)
    try {
      const response = activeViewMode === 'global'
        ? await api.getGlobalObsValues(apiBase, { column, indices })
        : await api.getObsValues(apiBase, selectedObjectId, { column, indices })
      const map: Record<number, number | string | null> = {}
      for (const v of response.values) map[v.index] = v.value
      set({ obsColorValues: map })
    } catch {
      set({ obsColorValues: {} })
    }
  },

  // F-08 — Differential expression
  setDeTargetClusters(clusters) { set({ deTargetClusters: clusters }) },
  setDeReferenceClusters(clusters) { set({ deReferenceClusters: clusters }) },
  toggleDeTargetCluster(clusterId) {
    set((state) => ({
      deTargetClusters: state.deTargetClusters.includes(clusterId)
        ? state.deTargetClusters.filter((c) => c !== clusterId)
        : [...state.deTargetClusters, clusterId]
    }))
  },
  toggleDeReferenceCluster(clusterId) {
    set((state) => ({
      deReferenceClusters: state.deReferenceClusters.includes(clusterId)
        ? state.deReferenceClusters.filter((c) => c !== clusterId)
        : [...state.deReferenceClusters, clusterId]
    }))
  },
  async runDifferentialExpression() {
    const { selectedObjectId, apiBase, clusterKey, deTargetClusters, deReferenceClusters } = get()
    if (!selectedObjectId || deTargetClusters.length === 0) {
      set({ error: 'Select at least one target cluster for DE analysis.' })
      return
    }
    set({ busy: true, busyMessage: 'Running differential expression', error: undefined, deResult: undefined })
    try {
      const result = await api.differentialExpression(apiBase, selectedObjectId, {
        cluster_key: clusterKey,
        target_clusters: deTargetClusters,
        reference_clusters: deReferenceClusters,
      })
      set({ deResult: result, busy: false, busyMessage: undefined })
    } catch (error) {
      set({ busy: false, busyMessage: undefined, error: error instanceof Error ? error.message : String(error) })
    }
  },

  // F-09 — Annotation export
  downloadExportAnnotations(fmt) {
    const { selectedObjectId, apiBase, sessionId } = get()
    if (!selectedObjectId) return
    const url = api.exportAnnotationsUrl(apiBase, selectedObjectId, fmt, sessionId)
    const a = document.createElement('a')
    a.href = url
    a.download = `annotations_${selectedObjectId}.${fmt}`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
  },

  // F-10 — Project dashboard
  async loadDashboard() {
    const { apiBase } = get()
    set({ busy: true, busyMessage: 'Loading project dashboard', error: undefined, dashboardData: undefined, dashboardVisible: true })
    try {
      const data = await api.getDashboard(apiBase)
      set({ dashboardData: data, busy: false, busyMessage: undefined })
    } catch (error) {
      set({ busy: false, busyMessage: undefined, dashboardVisible: false, error: error instanceof Error ? error.message : String(error) })
    }
  },
  setDashboardVisible(visible) { set({ dashboardVisible: visible }) },

  // F-15 — Annotation diff
  async runAnnotationDiff(keyA, keyB) {
    const { selectedObjectId, apiBase } = get()
    if (!selectedObjectId) {
      set({ error: 'Select an object first.' })
      return
    }
    set({ busy: true, busyMessage: 'Comparing annotations', error: undefined, annotationDiffResult: undefined })
    try {
      const result = await api.annotationDiff(apiBase, selectedObjectId, { key_a: keyA, key_b: keyB })
      set({ annotationDiffResult: result, busy: false, busyMessage: undefined })
    } catch (error) {
      set({ busy: false, busyMessage: undefined, error: error instanceof Error ? error.message : String(error) })
    }
  },

  // F-03 — Persistent session recovery
  async checkLiveSession() {
    const { selectedObjectId, apiBase } = get()
    if (!selectedObjectId) return
    try {
      const info = await api.getLiveSession(apiBase, selectedObjectId)
      set({ liveSessionInfo: info })
    } catch {
      set({ liveSessionInfo: undefined })
    }
  },
  async restoreLiveSession() {
    const { selectedObjectId, apiBase, embeddingKey, clusterKey, maxPoints, minPerCluster, maxPerCluster } = get()
    if (!selectedObjectId) return
    set({ busy: true, busyMessage: 'Restoring session', error: undefined })
    try {
      const summary = await api.restoreLiveSession(apiBase, selectedObjectId)
      set({ sessionSummary: summary, sessionId: summary.session_id, liveSessionInfo: undefined })
      // Reload UMAP so annotation colors from restored session are visible
      const response = await api.getUmap(apiBase, selectedObjectId, {
        embedding_key: embeddingKey,
        cluster_key: clusterKey || null,
        gene_name: null,
        max_points: maxPoints,
        min_per_cluster: minPerCluster,
        max_per_cluster: maxPerCluster,
        random_seed: 13
      })
      set({ points: response.points, viewToken: response.view_token ?? null, busy: false, busyMessage: undefined })
    } catch (error) {
      set({ busy: false, error: error instanceof Error ? error.message : String(error) })
    }
  },
  async dismissLiveSession() {
    const { selectedObjectId, apiBase } = get()
    if (!selectedObjectId) return
    try {
      await api.clearLiveSession(apiBase, selectedObjectId)
    } catch { /* ignore */ }
    set({ liveSessionInfo: undefined })
  }
}))
