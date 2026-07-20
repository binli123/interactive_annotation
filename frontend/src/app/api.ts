import type {
  AnnotationDiffResponse,
  CapabilitiesResponse,
  ClusterLabelEditorResponse,
  DEResponse,
  DotplotResponse,
  GeneCatalogResponse,
  GeneExpressionResponse,
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
  ObsColumnsResponse,
  ObsValuesResponse,
  PolygonSelectResponse,
  PropagateResponse,
  PointClusterResponse,
  ReferencePropagateResponse,
  PromoteReannotLabelsResponse,
  SaveClusterLabelsResponse,
  SaveResponse,
  SessionSummary,
  UmapResponse,
  VisibleHighlightResponse
} from './types'

const activeRequestControllers = new Set<AbortController>()

export function abortActiveRequests() {
  for (const controller of activeRequestControllers) {
    controller.abort()
  }
  activeRequestControllers.clear()
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController()
  activeRequestControllers.add(controller)
  let response: Response
  try {
    response = await fetch(url, {
      headers: {
        'Content-Type': 'application/json',
        ...(init?.headers ?? {})
      },
      ...init,
      signal: controller.signal
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new Error('Stopped current request.')
    }
    throw error
  } finally {
    activeRequestControllers.delete(controller)
  }
  if (!response.ok) {
    const text = await response.text()
    throw new Error(text || `Request failed: ${response.status}`)
  }
  return (await response.json()) as T
}

export const api = {
  getCapabilities(baseUrl: string) {
    return requestJson<CapabilitiesResponse>(`${baseUrl}/capabilities`)
  },
  scanFolder(baseUrl: string, folderPath: string) {
    return requestJson<ObjectCard[]>(`${baseUrl}/scan-folder`, {
      method: 'POST',
      body: JSON.stringify({ folder_path: folderPath })
    })
  },
  listObjects(baseUrl: string) {
    return requestJson<ObjectCard[]>(`${baseUrl}/objects`)
  },
  getMetadata(baseUrl: string, objectId: string) {
    return requestJson<MetadataResponse>(`${baseUrl}/objects/${objectId}/metadata`)
  },
  getGlobalMetadata(baseUrl: string) {
    return requestJson<MetadataResponse>(`${baseUrl}/global/metadata`)
  },
  getGlobalGenes(baseUrl: string) {
    return requestJson<GeneCatalogResponse>(`${baseUrl}/global/genes`)
  },
  getGenes(baseUrl: string, objectId: string) {
    return requestJson<GeneCatalogResponse>(`${baseUrl}/objects/${objectId}/genes`)
  },
  getGeneExpression(baseUrl: string, objectId: string, payload: { gene_name: string; view_token?: string | null; indices?: number[] }) {
    return requestJson<GeneExpressionResponse>(`${baseUrl}/objects/${objectId}/gene-expression`, {
      method: 'POST',
      body: JSON.stringify(payload)
    })
  },
  getGlobalGeneExpression(baseUrl: string, payload: { gene_name: string; view_token?: string | null; indices?: number[] }) {
    return requestJson<GeneExpressionResponse>(`${baseUrl}/global/gene-expression`, {
      method: 'POST',
      body: JSON.stringify(payload)
    })
  },
  getPointClusters(baseUrl: string, objectId: string, payload: { cluster_key: string; indices: number[] }) {
    return requestJson<PointClusterResponse>(`${baseUrl}/objects/${objectId}/point-clusters`, {
      method: 'POST',
      body: JSON.stringify(payload)
    })
  },
  getGlobalPointClusters(baseUrl: string, payload: { cluster_key: string; indices: number[] }) {
    return requestJson<PointClusterResponse>(`${baseUrl}/global/point-clusters`, {
      method: 'POST',
      body: JSON.stringify(payload)
    })
  },
  getClusterLabelEditor(baseUrl: string, objectId: string, clusterKey: string) {
    return requestJson<ClusterLabelEditorResponse>(
      `${baseUrl}/objects/${objectId}/cluster-label-editor?cluster_key=${encodeURIComponent(clusterKey)}`
    )
  },
  saveClusterLabelEditor(
    baseUrl: string,
    objectId: string,
    payload: {
      cluster_key: string
      display_column?: string | null
      mapping: Record<string, string>
    }
  ) {
    return requestJson<SaveClusterLabelsResponse>(`${baseUrl}/objects/${objectId}/cluster-label-editor`, {
      method: 'POST',
      body: JSON.stringify(payload)
    })
  },
  getMarkerDotplot(
    baseUrl: string,
    objectId: string,
    payload: {
      cluster_key: string
      genes: string[]
      save_to_object_dir?: boolean
      output_name?: string | null
    }
  ) {
    return requestJson<DotplotResponse>(`${baseUrl}/objects/${objectId}/marker-dotplot`, {
      method: 'POST',
      body: JSON.stringify(payload)
    })
  },
  getGlobalMarkerDotplot(
    baseUrl: string,
    payload: {
      cluster_key: string
      genes: string[]
      save_to_object_dir?: boolean
      output_name?: string | null
    }
  ) {
    return requestJson<DotplotResponse>(`${baseUrl}/global/marker-dotplot`, {
      method: 'POST',
      body: JSON.stringify(payload)
    })
  },
  referencePropagate(
    baseUrl: string,
    objectId: string,
    payload: {
      cluster_key: string
      reference_clusters: string[]
      source_clusters: string[]
      output_name: string
      n_neighbors: number
    }
  ) {
    return requestJson<ReferencePropagateResponse>(`${baseUrl}/objects/${objectId}/reference-propagate`, {
      method: 'POST',
      body: JSON.stringify(payload)
    })
  },
  discoverMarkers(
    baseUrl: string,
    objectId: string,
    payload: {
      cluster_key: string
      active_clusters: string[]
      target_clusters: string[]
      top_n: number
    }
  ) {
    return requestJson<MarkerDiscoveryResponse>(`${baseUrl}/objects/${objectId}/discover-markers`, {
      method: 'POST',
      body: JSON.stringify(payload)
    })
  },
  getUmap(
    baseUrl: string,
    objectId: string,
    payload: {
      embedding_key: string
      cluster_key?: string | null
      gene_name?: string | null
      max_points: number
      min_per_cluster: number
      max_per_cluster: number
      random_seed: number
    }
  ) {
    return requestJson<UmapResponse>(`${baseUrl}/objects/${objectId}/umap`, {
      method: 'POST',
      body: JSON.stringify(payload)
    })
  },
  getGlobalUmap(
    baseUrl: string,
    payload: {
      embedding_key: string
      cluster_key?: string | null
      gene_name?: string | null
      max_points: number
      min_per_cluster: number
      max_per_cluster: number
      random_seed: number
    }
  ) {
    return requestJson<UmapResponse>(`${baseUrl}/global/umap`, {
      method: 'POST',
      body: JSON.stringify(payload)
    })
  },
  getGlobalUmapCombined(
    baseUrl: string,
    payload: {
      embedding_key: string
      cluster_key?: string | null
      gene_name?: string | null
      max_points: number
      min_per_cluster: number
      max_per_cluster: number
      random_seed: number
    }
  ) {
    return requestJson<UmapResponse>(`${baseUrl}/global/umap-combined`, {
      method: 'POST',
      body: JSON.stringify(payload)
    })
  },
  highlightGlobalFromObject(
    baseUrl: string,
    payload: {
      source_object_id: string
      source_cluster_key: string
      source_cluster_id: string
      embedding_key: string
      cluster_key?: string | null
      max_points: number
      min_per_cluster: number
      max_per_cluster: number
      random_seed: number
    }
  ) {
    return requestJson<UmapResponse>(`${baseUrl}/global/highlight-from-object`, {
      method: 'POST',
      body: JSON.stringify(payload)
    })
  },
  highlightVisibleGlobalFromObject(
    baseUrl: string,
    payload: {
      source_object_id: string
      source_cluster_key: string
      source_cluster_id: string
      indices: number[]
    }
  ) {
    return requestJson<VisibleHighlightResponse>(`${baseUrl}/global/highlight-visible-from-object`, {
      method: 'POST',
      body: JSON.stringify(payload)
    })
  },
  polygonSelect(
    baseUrl: string,
    objectId: string,
    payload: Record<string, unknown>
  ) {
    return requestJson<PolygonSelectResponse>(`${baseUrl}/objects/${objectId}/polygon-select`, {
      method: 'POST',
      body: JSON.stringify(payload)
    })
  },
  seedLabels(
    baseUrl: string,
    objectId: string,
    payload: Record<string, unknown>
  ) {
    return requestJson<SessionSummary>(`${baseUrl}/objects/${objectId}/seed-labels`, {
      method: 'POST',
      body: JSON.stringify(payload)
    })
  },
  propagate(
    baseUrl: string,
    objectId: string,
    payload: Record<string, unknown>
  ) {
    return requestJson<PropagateResponse>(`${baseUrl}/objects/${objectId}/propagate`, {
      method: 'POST',
      body: JSON.stringify(payload)
    })
  },
  sessionSummary(baseUrl: string, objectId: string, sessionId: string) {
    return requestJson<SessionSummary>(
      `${baseUrl}/objects/${objectId}/session-summary?session_id=${encodeURIComponent(sessionId)}`
    )
  },
  clearSession(baseUrl: string, objectId: string, sessionId: string) {
    return requestJson<{ status: string; session_id: string }>(
      `${baseUrl}/objects/${objectId}/clear-session?session_id=${encodeURIComponent(sessionId)}`,
      { method: 'POST' }
    )
  },
  save(baseUrl: string, objectId: string, payload: Record<string, unknown>) {
    return requestJson<SaveResponse>(`${baseUrl}/objects/${objectId}/save`, {
      method: 'POST',
      body: JSON.stringify(payload)
    })
  },
  moveCluster(
    baseUrl: string,
    objectId: string,
    payload: {
      destination_object_id: string
      cluster_key: string
      cluster_id: string
      allow_overwrite?: boolean
    }
  ) {
    return requestJson<MoveClusterResponse>(`${baseUrl}/objects/${objectId}/move-cluster`, {
      method: 'POST',
      body: JSON.stringify(payload)
    })
  },
  getMoveClusterUndoStatus(baseUrl: string) {
    return requestJson<MoveClusterUndoStatusResponse>(`${baseUrl}/move-cluster-undo`)
  },
  undoMoveCluster(baseUrl: string) {
    return requestJson<MoveClusterUndoResponse>(`${baseUrl}/move-cluster-undo`, {
      method: 'POST'
    })
  },
  getObjectUndoStatus(baseUrl: string) {
    return requestJson<ObjectChangeUndoStatusResponse>(`${baseUrl}/object-change-undo`)
  },
  undoObjectChange(baseUrl: string) {
    return requestJson<ObjectChangeUndoResponse>(`${baseUrl}/object-change-undo`, {
      method: 'POST'
    })
  },
  previewMoveCluster(
    baseUrl: string,
    objectId: string,
    payload: {
      destination_object_id: string
      cluster_key: string
      cluster_id: string
    }
  ) {
    return requestJson<MoveClusterPreviewResponse>(`${baseUrl}/objects/${objectId}/move-cluster-preview`, {
      method: 'POST',
      body: JSON.stringify(payload)
    })
  },
  promoteReannotNew(baseUrl: string, objectId: string) {
    return requestJson<PromoteReannotLabelsResponse>(`${baseUrl}/objects/${objectId}/promote-reannot-new`, {
      method: 'POST'
    })
  },

  // F-04 / F-13 — Obs metadata coloring & QC
  getObsColumns(baseUrl: string, objectId: string) {
    return requestJson<ObsColumnsResponse>(`${baseUrl}/objects/${objectId}/obs-columns`)
  },
  getGlobalObsColumns(baseUrl: string) {
    return requestJson<ObsColumnsResponse>(`${baseUrl}/global/obs-columns`)
  },
  getObsValues(baseUrl: string, objectId: string, payload: { column: string; indices: number[] }) {
    return requestJson<ObsValuesResponse>(`${baseUrl}/objects/${objectId}/obs-values`, {
      method: 'POST',
      body: JSON.stringify(payload)
    })
  },
  getGlobalObsValues(baseUrl: string, payload: { column: string; indices: number[] }) {
    return requestJson<ObsValuesResponse>(`${baseUrl}/global/obs-values`, {
      method: 'POST',
      body: JSON.stringify(payload)
    })
  },

  // F-08 — Differential expression
  differentialExpression(
    baseUrl: string,
    objectId: string,
    payload: {
      cluster_key: string
      target_clusters: string[]
      reference_clusters: string[]
      top_n?: number
      method?: 'wilcoxon' | 't-test'
    }
  ) {
    return requestJson<DEResponse>(`${baseUrl}/objects/${objectId}/differential-expression`, {
      method: 'POST',
      body: JSON.stringify(payload)
    })
  },

  // F-09 — Annotation export (returns URL for direct download)
  exportAnnotationsUrl(baseUrl: string, objectId: string, fmt: 'csv' | 'tsv' | 'json', sessionId?: string): string {
    const params = new URLSearchParams({ fmt })
    if (sessionId) params.set('session_id', sessionId)
    return `${baseUrl}/objects/${objectId}/export-annotations?${params}`
  },

  // F-10 — Project dashboard
  getDashboard(baseUrl: string) {
    return requestJson<ObjectAnnotationCoverage[]>(`${baseUrl}/dashboard`)
  },
  getObjectCoverage(baseUrl: string, objectId: string) {
    return requestJson<ObjectAnnotationCoverage>(`${baseUrl}/objects/${objectId}/coverage`)
  },

  // F-15 — Annotation diff
  annotationDiff(baseUrl: string, objectId: string, payload: { key_a: string; key_b: string }) {
    return requestJson<AnnotationDiffResponse>(`${baseUrl}/objects/${objectId}/annotation-diff`, {
      method: 'POST',
      body: JSON.stringify(payload)
    })
  },

  // F-03 — Persistent session recovery
  getLiveSession(baseUrl: string, objectId: string) {
    return requestJson<LiveSessionResponse>(`${baseUrl}/objects/${objectId}/live-session`)
  },
  restoreLiveSession(baseUrl: string, objectId: string) {
    return requestJson<SessionSummary>(`${baseUrl}/objects/${objectId}/restore-live-session`, {
      method: 'POST'
    })
  },
  clearLiveSession(baseUrl: string, objectId: string) {
    return requestJson<{ status: string; object_id: string }>(`${baseUrl}/objects/${objectId}/live-session`, {
      method: 'DELETE'
    })
  }
}
