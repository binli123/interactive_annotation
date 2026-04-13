export type ObjectCard = {
  object_id: string
  lineage_name: string
  object_path: string
  lineage_dir: string
  n_cells?: number | null
  n_genes?: number | null
  is_valid: boolean
  validation_error?: string | null
  resolution_trials: Array<Record<string, unknown>>
}

export type MetadataResponse = {
  object_id: string
  lineage_name: string
  object_path: string
  shape: [number, number]
  cluster_keys: string[]
  embedding_keys: string[]
  pca_keys: string[]
  default_embedding_key: string
  default_cluster_key?: string | null
  has_connectivities: boolean
  has_distances: boolean
  summary_resolution_trials: Array<Record<string, unknown>>
  obs_columns: string[]
  sample_columns: string[]
  manifest: Record<string, unknown>
}

export type UmapPoint = {
  index: number
  obs_name: string
  cell_id: string
  x: number
  y: number
  cluster: string
  sample_id?: string | null
  region?: string | null
  lineage?: string | null
  current_label?: string | null
  current_score?: number | null
  gene_expression?: number | null
  is_highlighted?: boolean | null
}

export type UmapResponse = {
  object_id: string
  embedding_key: string
  cluster_key?: string | null
  gene_name?: string | null
  total_cells: number
  displayed_cells: number
  highlighted_total?: number | null
  highlighted_displayed?: number | null
  points: UmapPoint[]
}

export type VisibleHighlightResponse = {
  object_id: string
  highlighted_total: number
  highlighted_displayed: number
  values: Array<{
    index: number
    is_highlighted: boolean
  }>
}

export type PolygonGeometry = {
  polygon_id: string
  vertices: number[][]
}

export type PolygonSelectionSummary = {
  polygon_id: string
  n_cells: number
  clusters: Array<{
    cluster: string
    n_cells: number
  }>
}

export type PolygonSelectResponse = {
  total_selected_cells: number
  selected_indices: number[]
  selected_cell_ids: string[]
  polygon_summaries: PolygonSelectionSummary[]
}

export type PolygonRecord = {
  id: string
  vertices: number[][]
  clusterId: string
  clusterName: string
  includeForPropagation: boolean
  nCells: number
  clusterSummary: Array<{
    cluster: string
    n_cells: number
  }>
}

export type PaletteName = 'bright' | 'earth' | 'pastel'

export type SessionSummary = {
  session_id: string
  object_id: string
  embedding_key: string
  cluster_key: string
  n_seed_cells: number
  n_polygons: number
  labels: Record<string, number>
  last_propagation?: Record<string, unknown> | null
}

export type PropagatedCell = {
  index: number
  obs_name: string
  cell_id: string
  predicted_label: string
  score: number
  margin: number
  is_seed: boolean
  is_assigned: boolean
}

export type ClusterSummaryRow = {
  cluster: string
  predicted_label: string
  n_cells: number
  n_assigned: number
  purity: number
  mean_score: number
}

export type PropagateResponse = {
  session_id: string
  method: string
  scope: string
  annotate_all: boolean
  graph_smoothing: number
  n_seed_cells: number
  n_eligible_cells: number
  n_assigned_cells: number
  label_counts: Record<string, number>
  cells: PropagatedCell[]
  cluster_summary: ClusterSummaryRow[]
}

export type SaveResponse = {
  object_path: string
  session_json_path: string
  polygons_geojson_path: string
  summary_csv_path: string
}

export type PromoteReannotLabelsResponse = {
  object_id: string
  object_path: string
  source_label_key: string
  source_display_key: string
  target_label_key: string
  target_display_key: string
}

export type ClusterLabelRow = {
  cluster_id: string
  n_cells: number
  display_name?: string | null
}

export type ClusterLabelEditorResponse = {
  object_id: string
  object_path: string
  cluster_key: string
  display_column: string
  rows: ClusterLabelRow[]
}

export type SaveClusterLabelsResponse = {
  object_id: string
  object_path: string
  cluster_key: string
  display_column: string
  n_updated: number
}

export type MoveClusterResponse = {
  source_object_id: string
  source_object_path: string
  destination_object_id: string
  destination_object_path: string
  cluster_key: string
  cluster_id: string
  display_name: string
  n_moved_cells: number
  n_overwritten_cells: number
}

export type MoveClusterPreviewResponse = {
  source_object_id: string
  source_object_path: string
  destination_object_id: string
  destination_object_path: string
  cluster_key: string
  source_cluster_id: string
  assigned_cluster_id: string
  display_name: string
  n_moved_cells: number
  n_overwritten_cells: number
}

export type MoveClusterUndoStatusResponse = {
  available: boolean
  source_object_id?: string | null
  source_object_path?: string | null
  destination_object_id?: string | null
  destination_object_path?: string | null
  cluster_key?: string | null
  source_cluster_id?: string | null
  assigned_cluster_id?: string | null
  display_name?: string | null
  n_moved_cells?: number | null
  n_overwritten_cells?: number | null
  created_at?: string | null
}

export type MoveClusterUndoResponse = {
  available: boolean
  restored: boolean
  source_object_id: string
  source_object_path: string
  destination_object_id: string
  destination_object_path: string
  cluster_key: string
  source_cluster_id: string
  assigned_cluster_id: string
  display_name: string
  n_moved_cells: number
  n_overwritten_cells: number
  created_at: string
}

export type GeneCatalogResponse = {
  object_id: string
  object_path: string
  genes: string[]
}

export type GeneExpressionResponse = {
  object_id: string
  gene_name: string
  values: Array<{
    index: number
    value: number
  }>
}

export type PointClusterResponse = {
  object_id: string
  cluster_key: string
  values: Array<{
    index: number
    cluster: string
  }>
}

export type ReferencePropagateResponse = {
  object_id: string
  object_path: string
  source_cluster_key: string
  new_cluster_key: string
  display_column: string
  n_reference_cells: number
  n_source_cells: number
  reference_clusters: string[]
  source_clusters: string[]
}

export type MarkerDiscoveryResponse = {
  object_id: string
  object_path: string
  cluster_key: string
  active_clusters: string[]
  target_clusters: string[]
  candidate_genes: string[]
}

export type DotplotResponse = {
  object_id: string
  object_path: string
  cluster_key: string
  display_group_key: string
  genes: string[]
  missing_genes: string[]
  image_base64: string
  saved_path?: string | null
}

export type PolygonFeatureCollection = {
  type: 'FeatureCollection'
  features: Array<{
    type: 'Feature'
    properties: Record<string, unknown>
    geometry: {
      type: 'Polygon'
      coordinates: number[][][]
    }
  }>
}
