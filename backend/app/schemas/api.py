from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ScanFolderRequest(BaseModel):
    folder_path: str | None = None


class ObjectCard(BaseModel):
    object_id: str
    lineage_name: str
    object_path: str
    lineage_dir: str
    n_cells: int | None = None
    n_genes: int | None = None
    is_valid: bool = True
    validation_error: str | None = None
    resolution_trials: list[dict[str, Any]] = Field(default_factory=list)


class MetadataResponse(BaseModel):
    object_id: str
    lineage_name: str
    object_path: str
    shape: tuple[int, int]
    cluster_keys: list[str]
    embedding_keys: list[str]
    pca_keys: list[str]
    default_embedding_key: str
    default_cluster_key: str | None = None
    has_connectivities: bool
    has_distances: bool
    summary_resolution_trials: list[dict[str, Any]] = Field(default_factory=list)
    obs_columns: list[str] = Field(default_factory=list)
    sample_columns: list[str] = Field(default_factory=list)
    manifest: dict[str, Any] = Field(default_factory=dict)


class UmapRequest(BaseModel):
    embedding_key: str
    cluster_key: str | None = None
    gene_name: str | None = None
    max_points: int = 50000
    min_per_cluster: int = 250
    max_per_cluster: int = 0
    random_seed: int = 13


class UmapPoint(BaseModel):
    index: int
    obs_name: str
    cell_id: str
    x: float
    y: float
    cluster: str
    sample_id: str | None = None
    region: str | None = None
    lineage: str | None = None
    current_label: str | None = None
    current_score: float | None = None
    gene_expression: float | None = None
    is_highlighted: bool | None = None


class UmapResponse(BaseModel):
    object_id: str
    embedding_key: str
    cluster_key: str | None
    gene_name: str | None = None
    total_cells: int
    displayed_cells: int
    highlighted_total: int | None = None
    highlighted_displayed: int | None = None
    points: list[UmapPoint]


class GeneCatalogResponse(BaseModel):
    object_id: str
    object_path: str
    genes: list[str]


class GeneExpressionRequest(BaseModel):
    gene_name: str
    indices: list[int] = Field(default_factory=list)


class GeneExpressionValue(BaseModel):
    index: int
    value: float


class GeneExpressionResponse(BaseModel):
    object_id: str
    gene_name: str
    values: list[GeneExpressionValue]


class PointClusterRequest(BaseModel):
    cluster_key: str
    indices: list[int] = Field(default_factory=list)


class PointClusterValue(BaseModel):
    index: int
    cluster: str


class PointClusterResponse(BaseModel):
    object_id: str
    cluster_key: str
    values: list[PointClusterValue]


class VisibleHighlightRequest(BaseModel):
    source_object_id: str
    source_cluster_key: str
    source_cluster_id: str
    indices: list[int] = Field(default_factory=list)


class VisibleHighlightValue(BaseModel):
    index: int
    is_highlighted: bool


class VisibleHighlightResponse(BaseModel):
    object_id: str
    highlighted_total: int
    highlighted_displayed: int
    values: list[VisibleHighlightValue]


class ReferencePropagateRequest(BaseModel):
    cluster_key: str
    reference_clusters: list[str] = Field(default_factory=list)
    source_clusters: list[str] = Field(default_factory=list)
    output_name: str = "new"
    n_neighbors: int = 15


class ReferencePropagateResponse(BaseModel):
    object_id: str
    object_path: str
    source_cluster_key: str
    new_cluster_key: str
    display_column: str
    n_reference_cells: int
    n_source_cells: int
    reference_clusters: list[str]
    source_clusters: list[str]


class MarkerDiscoveryRequest(BaseModel):
    cluster_key: str
    active_clusters: list[str] = Field(default_factory=list)
    target_clusters: list[str] = Field(default_factory=list)
    top_n: int = Field(default=10, ge=1, le=200)


class MarkerDiscoveryResponse(BaseModel):
    object_id: str
    object_path: str
    cluster_key: str
    active_clusters: list[str]
    target_clusters: list[str]
    candidate_genes: list[str]


class DotplotRequest(BaseModel):
    cluster_key: str
    genes: list[str] = Field(default_factory=list)
    save_to_object_dir: bool = False
    output_name: str | None = None


class DotplotResponse(BaseModel):
    object_id: str
    object_path: str
    cluster_key: str
    display_group_key: str
    genes: list[str]
    missing_genes: list[str] = Field(default_factory=list)
    image_base64: str
    saved_path: str | None = None


class PolygonGeometry(BaseModel):
    polygon_id: str
    vertices: list[list[float]]


class PolygonSelectRequest(BaseModel):
    embedding_key: str
    polygons: list[PolygonGeometry]
    cluster_key: str | None = None


class ClusterCount(BaseModel):
    cluster: str
    n_cells: int


class PolygonSelectionSummary(BaseModel):
    polygon_id: str
    n_cells: int
    clusters: list[ClusterCount]


class PolygonSelectResponse(BaseModel):
    total_selected_cells: int
    selected_indices: list[int]
    selected_cell_ids: list[str]
    polygon_summaries: list[PolygonSelectionSummary]


class SeedLabelsRequest(BaseModel):
    session_id: str
    embedding_key: str
    cluster_key: str
    label: str
    display_name: str | None = None
    notes: str | None = None
    polygons: list[PolygonGeometry]


class SessionSummaryResponse(BaseModel):
    session_id: str
    object_id: str
    embedding_key: str
    cluster_key: str
    n_seed_cells: int
    n_polygons: int
    labels: dict[str, int]
    last_propagation: dict[str, Any] | None = None


class PropagateRequest(BaseModel):
    session_id: str
    embedding_key: str
    cluster_key: str
    method: Literal["graph_diffusion", "knn_vote"] = "knn_vote"
    scope: Literal[
        "polygon_only",
        "selected_clusters_only",
        "same_connected_neighborhood",
        "whole_lineage",
    ] = "selected_clusters_only"
    min_score: float = 0.7
    min_margin: float = 0.1
    annotate_all: bool = True
    graph_smoothing: float = Field(default=0.0, ge=0.0, le=1.0)
    n_neighbors: int = 15
    neighborhood_hops: int = 2


class PropagatedCell(BaseModel):
    index: int
    obs_name: str
    cell_id: str
    predicted_label: str
    score: float
    margin: float
    is_seed: bool
    is_assigned: bool


class ClusterSummaryRow(BaseModel):
    cluster: str
    predicted_label: str
    n_cells: int
    n_assigned: int
    purity: float
    mean_score: float


class PropagateResponse(BaseModel):
    session_id: str
    method: str
    scope: str
    annotate_all: bool
    graph_smoothing: float
    n_seed_cells: int
    n_eligible_cells: int
    n_assigned_cells: int
    label_counts: dict[str, int]
    cells: list[PropagatedCell]
    cluster_summary: list[ClusterSummaryRow]


class SaveRequest(BaseModel):
    session_id: str
    output_dir: str | None = None
    output_prefix: str | None = None


class SaveResponse(BaseModel):
    object_path: str
    session_json_path: str
    polygons_geojson_path: str
    summary_csv_path: str


class PromoteReannotLabelsResponse(BaseModel):
    object_id: str
    object_path: str
    source_label_key: str
    source_display_key: str
    target_label_key: str
    target_display_key: str


class ClusterLabelRow(BaseModel):
    cluster_id: str
    n_cells: int
    display_name: str | None = None


class ClusterLabelEditorResponse(BaseModel):
    object_id: str
    object_path: str
    cluster_key: str
    display_column: str
    rows: list[ClusterLabelRow]


class SaveClusterLabelsRequest(BaseModel):
    cluster_key: str
    display_column: str | None = None
    mapping: dict[str, str] = Field(default_factory=dict)


class SaveClusterLabelsResponse(BaseModel):
    object_id: str
    object_path: str
    cluster_key: str
    display_column: str
    n_updated: int


class HighlightGlobalRequest(BaseModel):
    source_object_id: str
    source_cluster_key: str
    source_cluster_id: str
    embedding_key: str
    cluster_key: str | None = None
    max_points: int = 50000
    min_per_cluster: int = 250
    max_per_cluster: int = 0
    random_seed: int = 13


class MoveClusterRequest(BaseModel):
    destination_object_id: str
    cluster_key: str
    cluster_id: str
    allow_overwrite: bool = False


class MoveClusterPreviewResponse(BaseModel):
    source_object_id: str
    source_object_path: str
    destination_object_id: str
    destination_object_path: str
    cluster_key: str
    source_cluster_id: str
    assigned_cluster_id: str
    display_name: str
    n_moved_cells: int
    n_overwritten_cells: int


class MoveClusterResponse(BaseModel):
    source_object_id: str
    source_object_path: str
    destination_object_id: str
    destination_object_path: str
    cluster_key: str
    cluster_id: str
    display_name: str
    n_moved_cells: int
    n_overwritten_cells: int


class MoveClusterUndoStatusResponse(BaseModel):
    available: bool
    source_object_id: str | None = None
    source_object_path: str | None = None
    destination_object_id: str | None = None
    destination_object_path: str | None = None
    cluster_key: str | None = None
    source_cluster_id: str | None = None
    assigned_cluster_id: str | None = None
    display_name: str | None = None
    n_moved_cells: int | None = None
    n_overwritten_cells: int | None = None
    created_at: str | None = None


class MoveClusterUndoResponse(BaseModel):
    available: bool
    restored: bool
    source_object_id: str
    source_object_path: str
    destination_object_id: str
    destination_object_path: str
    cluster_key: str
    source_cluster_id: str
    assigned_cluster_id: str
    display_name: str
    n_moved_cells: int
    n_overwritten_cells: int
    created_at: str
