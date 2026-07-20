from __future__ import annotations

from pathlib import Path

import anndata as ad
import h5py
import numpy as np
import pandas as pd
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.core.config import settings
from app.models.state import PolygonSeedBatch, PropagationSnapshot
from app.schemas.api import (
    AnnotationDiffRequest,
    AnnotationDiffResponse,
    ClusterLabelEditorResponse,
    DERequest,
    DEResponse,
    DotplotRequest,
    DotplotResponse,
    GeneCatalogResponse,
    GeneExpressionRequest,
    GeneExpressionResponse,
    HighlightGlobalRequest,
    LiveSessionResponse,
    MarkerDiscoveryRequest,
    MarkerDiscoveryResponse,
    MetadataResponse,
    MoveClusterRequest,
    MoveClusterPreviewResponse,
    MoveClusterResponse,
    MoveClusterUndoResponse,
    MoveClusterUndoStatusResponse,
    ObjectAnnotationCoverage,
    ObjectChangeUndoResponse,
    ObjectChangeUndoStatusResponse,
    ObjectCard,
    ObsColumnsResponse,
    ObsValuesRequest,
    ObsValuesResponse,
    PointClusterRequest,
    PointClusterResponse,
    PolygonSelectRequest,
    PolygonSelectResponse,
    PromoteReannotLabelsResponse,
    PropagateRequest,
    PropagateResponse,
    ReferencePropagateRequest,
    ReferencePropagateResponse,
    SaveRequest,
    SaveClusterLabelsRequest,
    SaveClusterLabelsResponse,
    SaveResponse,
    ScanFolderRequest,
    SessionSummaryResponse,
    SeedLabelsRequest,
    VisibleHighlightRequest,
    VisibleHighlightResponse,
    UmapRequest,
    UmapResponse,
)
from app.services.adata_service import adata_service
from app.services.propagation import (
    neighborhood_mask,
    run_graph_diffusion,
    run_knn_vote,
)
from app.services.registry import registry
from app.services.sessions import session_store

router = APIRouter()


def _object_card(record) -> ObjectCard:
    return ObjectCard(
        object_id=record.object_id,
        lineage_name=record.lineage_name,
        object_path=str(record.object_path),
        lineage_dir=str(record.lineage_dir),
        n_cells=record.n_cells,
        n_genes=record.n_genes,
        is_valid=record.is_valid,
        validation_error=record.validation_error,
        resolution_trials=record.resolution_trials,
    )


def _resolve_record(object_id: str):
    try:
        return registry.get(object_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _global_record():
    try:
        return registry.build_record(
            object_path=settings.default_global_object_path,
            lineage_name="Global",
            lineage_dir=settings.default_global_object_path.parent,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _validate_saved_h5ad(path: Path) -> None:
    required_keys = {"X", "obs", "var", "obsm", "uns"}
    try:
        with h5py.File(path, "r") as handle:
            missing = sorted(required_keys.difference(handle.keys()))
            if missing:
                raise ValueError(f"Missing required groups after save: {', '.join(missing)}")
    except Exception as exc:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
        raise HTTPException(
            status_code=500,
            detail=f"Saved object validation failed for {path}: {exc}",
        ) from exc


@router.get("/capabilities")
def capabilities():
    """Return feature flags based on what data is available on disk."""
    return {"has_global": settings.default_global_object_path.exists()}


@router.post("/scan-folder", response_model=list[ObjectCard])
def scan_folder(request: ScanFolderRequest) -> list[ObjectCard]:
    fallback_folder = settings.default_lineage_root
    requested_path = Path(request.folder_path).expanduser() if request.folder_path else None

    # If the user passed a direct path to a single .h5ad file, register just that file.
    if requested_path and requested_path.suffix == ".h5ad":
        try:
            records = registry.register_single(requested_path)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        for record in records:
            adata_service.invalidate_cached(record.object_id)
        return [_object_card(record) for record in records]

    if requested_path and not requested_path.exists() and str(requested_path) == "/data/lineages_current":
        folder = fallback_folder
    else:
        folder = requested_path or fallback_folder
    try:
        records = registry.scan(folder)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    for record in records:
        adata_service.invalidate_cached(record.object_id)
    return [_object_card(record) for record in records]


@router.get("/objects", response_model=list[ObjectCard])
def list_objects() -> list[ObjectCard]:
    return [_object_card(record) for record in registry.list_records()]


@router.get("/objects/{object_id}/metadata", response_model=MetadataResponse)
def object_metadata(object_id: str) -> MetadataResponse:
    record = _resolve_record(object_id)
    try:
        return MetadataResponse(**adata_service.get_metadata(record))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/objects/{object_id}/genes", response_model=GeneCatalogResponse)
def object_genes(object_id: str) -> GeneCatalogResponse:
    record = _resolve_record(object_id)
    return GeneCatalogResponse(**adata_service.get_gene_catalog(record))


@router.get("/global/metadata", response_model=MetadataResponse)
def global_metadata() -> MetadataResponse:
    record = _global_record()
    try:
        return MetadataResponse(**adata_service.get_metadata(record))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/global/umap", response_model=UmapResponse)
def global_umap(request: UmapRequest, background_tasks: BackgroundTasks) -> UmapResponse:
    record = _global_record()
    try:
        payload = adata_service.get_umap_points(
            record=record,
            embedding_key=request.embedding_key,
            cluster_key=request.cluster_key,
            gene_name=request.gene_name,
            max_points=request.max_points,
            min_per_cluster=request.min_per_cluster,
            max_per_cluster=request.max_per_cluster,
            random_seed=request.random_seed,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if payload.get("view_token"):
        background_tasks.add_task(adata_service.prewarm_view_submatrix, record, payload["view_token"])
    return UmapResponse(**payload)


@router.post("/global/umap-combined", response_model=UmapResponse)
def global_umap_combined(request: UmapRequest, background_tasks: BackgroundTasks) -> UmapResponse:
    record = _global_record()
    lineage_records = registry.list_records()
    try:
        payload = adata_service.get_combined_global_umap_points(
            global_record=record,
            lineage_records=lineage_records,
            embedding_key=request.embedding_key,
            cluster_key=request.cluster_key,
            max_points=request.max_points,
            min_per_cluster=request.min_per_cluster,
            max_per_cluster=request.max_per_cluster,
            random_seed=request.random_seed,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if payload.get("view_token"):
        background_tasks.add_task(adata_service.prewarm_view_submatrix, record, payload["view_token"])
    return UmapResponse(**payload)


@router.post("/global/highlight-from-object", response_model=UmapResponse)
def global_highlight_from_object(request: HighlightGlobalRequest) -> UmapResponse:
    source_record = _resolve_record(request.source_object_id)
    global_record = _global_record()
    try:
        highlight_cell_ids = adata_service.get_cluster_cell_ids(
            record=source_record,
            cluster_key=request.source_cluster_key,
            cluster_id=request.source_cluster_id,
        )
        payload = adata_service.get_umap_points_with_highlight(
            record=global_record,
            embedding_key=request.embedding_key,
            cluster_key=request.cluster_key,
            highlight_cell_ids=highlight_cell_ids,
            max_points=request.max_points,
            min_per_cluster=request.min_per_cluster,
            max_per_cluster=request.max_per_cluster,
            random_seed=request.random_seed,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return UmapResponse(**payload)


@router.post("/global/highlight-visible-from-object", response_model=VisibleHighlightResponse)
def global_highlight_visible_from_object(request: VisibleHighlightRequest) -> VisibleHighlightResponse:
    source_record = _resolve_record(request.source_object_id)
    global_record = _global_record()
    try:
        highlight_cell_ids = adata_service.get_cluster_cell_ids(
            record=source_record,
            cluster_key=request.source_cluster_key,
            cluster_id=request.source_cluster_id,
        )
        payload = adata_service.get_visible_highlight_values(
            record=global_record,
            highlight_cell_ids=highlight_cell_ids,
            indices=request.indices,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return VisibleHighlightResponse(**payload)


@router.post("/objects/{object_id}/gene-expression", response_model=GeneExpressionResponse)
def object_gene_expression(object_id: str, request: GeneExpressionRequest) -> GeneExpressionResponse:
    record = _resolve_record(object_id)
    try:
        payload = adata_service.get_gene_expression_values(
            record, request.gene_name, request.indices, view_token=request.view_token
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return GeneExpressionResponse(**payload)


@router.get("/global/genes", response_model=GeneCatalogResponse)
def global_genes() -> GeneCatalogResponse:
    record = _global_record()
    return GeneCatalogResponse(**adata_service.get_gene_catalog(record))


@router.post("/global/gene-expression", response_model=GeneExpressionResponse)
def global_gene_expression(request: GeneExpressionRequest) -> GeneExpressionResponse:
    record = _global_record()
    try:
        payload = adata_service.get_gene_expression_values(
            record, request.gene_name, request.indices, view_token=request.view_token
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return GeneExpressionResponse(**payload)


@router.post("/objects/{object_id}/point-clusters", response_model=PointClusterResponse)
def object_point_clusters(object_id: str, request: PointClusterRequest) -> PointClusterResponse:
    record = _resolve_record(object_id)
    try:
        payload = adata_service.get_point_cluster_values(record, request.cluster_key, request.indices)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PointClusterResponse(**payload)


@router.post("/global/point-clusters", response_model=PointClusterResponse)
def global_point_clusters(request: PointClusterRequest) -> PointClusterResponse:
    record = _global_record()
    try:
        payload = adata_service.get_point_cluster_values(record, request.cluster_key, request.indices)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PointClusterResponse(**payload)


@router.get("/objects/{object_id}/cluster-label-editor", response_model=ClusterLabelEditorResponse)
def cluster_label_editor(object_id: str, cluster_key: str) -> ClusterLabelEditorResponse:
    record = _resolve_record(object_id)
    try:
        payload = adata_service.get_cluster_label_editor(record, cluster_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ClusterLabelEditorResponse(**payload)


@router.post("/objects/{object_id}/cluster-label-editor", response_model=SaveClusterLabelsResponse)
def save_cluster_label_editor(object_id: str, request: SaveClusterLabelsRequest) -> SaveClusterLabelsResponse:
    record = _resolve_record(object_id)
    try:
        payload = adata_service.save_cluster_label_editor(
            record=record,
            cluster_key=request.cluster_key,
            mapping=request.mapping,
            display_column=request.display_column,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SaveClusterLabelsResponse(**payload)


@router.post("/objects/{object_id}/promote-reannot-new", response_model=PromoteReannotLabelsResponse)
def promote_reannot_new(object_id: str) -> PromoteReannotLabelsResponse:
    record = _resolve_record(object_id)
    try:
        payload = adata_service.promote_reannot_new_to_canonical(record)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PromoteReannotLabelsResponse(**payload)


@router.get("/objects/{object_id}/cluster-keys", response_model=list[str])
def cluster_keys(object_id: str) -> list[str]:
    record = _resolve_record(object_id)
    return adata_service.get_metadata(record)["cluster_keys"]


@router.get("/objects/{object_id}/embedding-keys", response_model=list[str])
def embedding_keys(object_id: str) -> list[str]:
    record = _resolve_record(object_id)
    return adata_service.get_metadata(record)["embedding_keys"]


@router.post("/objects/{object_id}/umap", response_model=UmapResponse)
def umap_points(object_id: str, request: UmapRequest, background_tasks: BackgroundTasks) -> UmapResponse:
    record = _resolve_record(object_id)
    try:
        payload = adata_service.get_umap_points(
            record=record,
            embedding_key=request.embedding_key,
            cluster_key=request.cluster_key,
            gene_name=request.gene_name,
            max_points=request.max_points,
            min_per_cluster=request.min_per_cluster,
            max_per_cluster=request.max_per_cluster,
            random_seed=request.random_seed,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if payload.get("view_token"):
        background_tasks.add_task(adata_service.prewarm_view_submatrix, record, payload["view_token"])
    return UmapResponse(**payload)


@router.post("/objects/{object_id}/marker-dotplot", response_model=DotplotResponse)
def marker_dotplot(object_id: str, request: DotplotRequest) -> DotplotResponse:
    record = _resolve_record(object_id)
    try:
        payload = adata_service.render_marker_dotplot(
            record=record,
            cluster_key=request.cluster_key,
            genes=request.genes,
            save_to_object_dir=request.save_to_object_dir,
            output_name=request.output_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return DotplotResponse(**payload)


@router.post("/global/marker-dotplot", response_model=DotplotResponse)
def global_marker_dotplot(request: DotplotRequest) -> DotplotResponse:
    record = _global_record()
    try:
        payload = adata_service.render_marker_dotplot(
            record=record,
            cluster_key=request.cluster_key,
            genes=request.genes,
            save_to_object_dir=request.save_to_object_dir,
            output_name=request.output_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return DotplotResponse(**payload)


@router.post("/objects/{object_id}/reference-propagate", response_model=ReferencePropagateResponse)
def reference_propagate(object_id: str, request: ReferencePropagateRequest) -> ReferencePropagateResponse:
    record = _resolve_record(object_id)
    try:
        payload = adata_service.reference_based_reannotate(
            record=record,
            cluster_key=request.cluster_key,
            reference_clusters=request.reference_clusters,
            source_clusters=request.source_clusters,
            output_name=request.output_name,
            n_neighbors=request.n_neighbors,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ReferencePropagateResponse(**payload)


@router.post("/objects/{object_id}/discover-markers", response_model=MarkerDiscoveryResponse)
def discover_markers(object_id: str, request: MarkerDiscoveryRequest) -> MarkerDiscoveryResponse:
    record = _resolve_record(object_id)
    try:
        payload = adata_service.discover_marker_genes(
            record=record,
            cluster_key=request.cluster_key,
            active_clusters=request.active_clusters,
            target_clusters=request.target_clusters,
            top_n=request.top_n,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return MarkerDiscoveryResponse(**payload)


@router.post("/objects/{object_id}/polygon-select", response_model=PolygonSelectResponse)
def polygon_select(object_id: str, request: PolygonSelectRequest) -> PolygonSelectResponse:
    record = _resolve_record(object_id)
    payload = adata_service.polygon_select(
        record=record,
        embedding_key=request.embedding_key,
        polygons=[polygon.model_dump() for polygon in request.polygons],
        cluster_key=request.cluster_key,
    )
    return PolygonSelectResponse(**payload)


@router.post("/objects/{object_id}/seed-labels", response_model=SessionSummaryResponse)
def seed_labels(object_id: str, request: SeedLabelsRequest) -> SessionSummaryResponse:
    record = _resolve_record(object_id)
    session = session_store.get_or_create(
        session_id=request.session_id,
        object_id=object_id,
        embedding_key=request.embedding_key,
        cluster_key=request.cluster_key,
    )
    for polygon in request.polygons:
        polygon_selection = adata_service.polygon_select(
            record=record,
            embedding_key=request.embedding_key,
            polygons=[polygon.model_dump()],
            cluster_key=request.cluster_key,
        )
        batch = PolygonSeedBatch(
            polygon_id=polygon.polygon_id,
            label=request.label,
            display_name=request.display_name,
            notes=request.notes,
            cell_indices=np.asarray(polygon_selection["selected_indices"], dtype=int),
            vertices=polygon.vertices,
        )
        session_store.register_batch(session.session_id, batch)

    session_store.persist(session.session_id, record.lineage_dir)
    return SessionSummaryResponse(**session_store.summarize(session.session_id))


def _eligible_mask(
    scope: str,
    graph,
    seed_mask: np.ndarray,
    cluster_values: np.ndarray,
    neighborhood_hops: int,
) -> np.ndarray:
    if scope == "polygon_only":
        return seed_mask.copy()
    if scope == "whole_lineage":
        return np.ones(seed_mask.shape[0], dtype=bool)
    if scope == "selected_clusters_only":
        seed_clusters = set(cluster_values[seed_mask].tolist())
        return np.isin(cluster_values, list(seed_clusters))
    if scope == "same_connected_neighborhood":
        if graph is None:
            return seed_mask.copy()
        return neighborhood_mask(graph, seed_mask, hops=neighborhood_hops)
    raise ValueError(f"Unsupported scope: {scope}")


@router.post("/objects/{object_id}/propagate", response_model=PropagateResponse)
def propagate(object_id: str, request: PropagateRequest) -> PropagateResponse:
    record = _resolve_record(object_id)
    session = session_store.get_or_create(
        session_id=request.session_id,
        object_id=object_id,
        embedding_key=request.embedding_key,
        cluster_key=request.cluster_key,
    )

    n_obs, obs_names, cluster_values, cell_ids = adata_service.get_obs_for_propagation(
        record, request.cluster_key
    )
    seed_labels = np.full(n_obs, "", dtype=object)
    for index, label in session.seed_labels.items():
        seed_labels[index] = label
    seed_mask = seed_labels != ""
    if not seed_mask.any():
        raise HTTPException(status_code=400, detail="No seed cells available in the session.")
    graph = adata_service.get_graph(record)
    eligible_mask = _eligible_mask(
        request.scope,
        graph,
        seed_mask,
        cluster_values,
        neighborhood_hops=request.neighborhood_hops,
    )

    # Only graph_diffusion consumes `graph` below — knn_vote fits its own (much
    # smaller) neighbor index over just the seed cells. Skip the expensive
    # whole-object graph build entirely when it won't be used.
    if graph is None and request.method == "graph_diffusion":
        graph = adata_service.get_or_build_knn_graph(record, request.n_neighbors)
    features = adata_service.get_features(record)

    if request.method == "graph_diffusion":
        result = run_graph_diffusion(
            graph=graph,
            seed_label_names=seed_labels,
            eligible_mask=eligible_mask,
            alpha=settings.diffusion_alpha,
            max_iter=settings.diffusion_max_iter,
            tol=settings.diffusion_tol,
            min_score=request.min_score,
            min_margin=request.min_margin,
            annotate_all=request.annotate_all,
            smoothing=request.graph_smoothing,
        )
    elif request.method == "knn_vote":
        result = run_knn_vote(
            features=features,
            seed_label_names=seed_labels,
            eligible_mask=eligible_mask,
            n_neighbors=request.n_neighbors,
            min_score=request.min_score,
            min_margin=request.min_margin,
            annotate_all=request.annotate_all,
        )
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported propagation method: {request.method}")

    snapshot = PropagationSnapshot(
        label_names=result.label_names,
        assigned_labels=result.assigned_labels,
        assigned_scores=result.scores,
        assigned_margins=result.margins,
        eligible_mask=result.eligible_mask,
        assigned_mask=result.assigned_mask,
        method=request.method,
        scope=request.scope,
        min_score=request.min_score,
        min_margin=request.min_margin,
        annotate_all=request.annotate_all,
        graph_smoothing=request.graph_smoothing,
        cluster_key=request.cluster_key,
    )
    session_store.attach_propagation(request.session_id, snapshot)

    label_counts = (
        pd.Series(result.assigned_labels[result.assigned_mask]).value_counts().sort_index().to_dict()
        if result.assigned_mask.any()
        else {}
    )
    cells = []
    for idx in np.flatnonzero(result.eligible_mask):
        cells.append(
            {
                "index": int(idx),
                "obs_name": str(obs_names[idx]),
                "cell_id": str(cell_ids[idx]),
                "predicted_label": str(result.assigned_labels[idx]),
                "score": float(result.scores[idx]),
                "margin": float(result.margins[idx]),
                "is_seed": bool(seed_mask[idx]),
                "is_assigned": bool(result.assigned_mask[idx]),
            }
        )

    cluster_summary = []
    eligible_clusters = pd.Series(cluster_values[result.eligible_mask], index=np.flatnonzero(result.eligible_mask))
    if not eligible_clusters.empty:
        for cluster, cluster_index in eligible_clusters.groupby(eligible_clusters).groups.items():
            member_indices = np.asarray(list(cluster_index), dtype=int)
            assigned_member_mask = result.assigned_mask[member_indices]
            assigned_labels = result.assigned_labels[member_indices][assigned_member_mask]
            if assigned_labels.size:
                majority = pd.Series(assigned_labels).value_counts()
                predicted_label = str(majority.index[0])
                purity = float(majority.iloc[0] / member_indices.size)
            else:
                predicted_label = "Unassigned"
                purity = 0.0
            cluster_summary.append(
                {
                    "cluster": str(cluster),
                    "predicted_label": predicted_label,
                    "n_cells": int(member_indices.size),
                    "n_assigned": int(assigned_member_mask.sum()),
                    "purity": purity,
                    "mean_score": float(result.scores[member_indices].mean()),
                }
            )

    session_store.persist(request.session_id, record.lineage_dir)
    return PropagateResponse(
        session_id=request.session_id,
        method=request.method,
        scope=request.scope,
        annotate_all=request.annotate_all,
        graph_smoothing=request.graph_smoothing,
        n_seed_cells=int(seed_mask.sum()),
        n_eligible_cells=int(result.eligible_mask.sum()),
        n_assigned_cells=int(result.assigned_mask.sum()),
        label_counts={str(key): int(value) for key, value in label_counts.items()},
        cells=cells,
        cluster_summary=cluster_summary,
    )


@router.post("/objects/{object_id}/clear-session")
def clear_session(object_id: str, session_id: str) -> dict[str, str]:
    _resolve_record(object_id)
    session_store.clear(session_id)
    return {"status": "cleared", "session_id": session_id}


@router.get("/objects/{object_id}/session-summary", response_model=SessionSummaryResponse)
def session_summary(object_id: str, session_id: str) -> SessionSummaryResponse:
    _resolve_record(object_id)
    try:
        return SessionSummaryResponse(**session_store.summarize(session_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/objects/{object_id}/save", response_model=SaveResponse)
def save_session(object_id: str, request: SaveRequest) -> SaveResponse:
    record = _resolve_record(object_id)
    try:
        session = session_store.get(request.session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        result = adata_service.save_propagation_results(record, session)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    session_json_path, polygons_geojson_path, summary_csv_path = session_store.save_sidecars(
        session_id=session.session_id,
        base_path=record.object_path.with_suffix(""),
        cluster_summary=result["cluster_summary"],
    )

    return SaveResponse(
        object_path=str(result["object_path"]),
        session_json_path=str(session_json_path),
        polygons_geojson_path=str(polygons_geojson_path),
        summary_csv_path=str(summary_csv_path),
    )


@router.post("/objects/{object_id}/move-cluster-preview", response_model=MoveClusterPreviewResponse)
def move_cluster_preview(object_id: str, request: MoveClusterRequest) -> MoveClusterPreviewResponse:
    source_record = _resolve_record(object_id)
    destination_record = _resolve_record(request.destination_object_id)
    try:
        payload = adata_service.preview_move_cluster_between_objects(
            source_record=source_record,
            destination_record=destination_record,
            cluster_key=request.cluster_key,
            cluster_id=request.cluster_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return MoveClusterPreviewResponse(**payload)


@router.post("/objects/{object_id}/move-cluster", response_model=MoveClusterResponse)
def move_cluster(object_id: str, request: MoveClusterRequest) -> MoveClusterResponse:
    source_record = _resolve_record(object_id)
    destination_record = _resolve_record(request.destination_object_id)
    try:
        payload = adata_service.move_cluster_between_objects(
            source_record=source_record,
            destination_record=destination_record,
            cluster_key=request.cluster_key,
            cluster_id=request.cluster_id,
            allow_overwrite=request.allow_overwrite,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    registry.scan(registry.scan_root or settings.default_lineage_root)
    return MoveClusterResponse(**payload)


@router.get("/move-cluster-undo", response_model=MoveClusterUndoStatusResponse)
def move_cluster_undo_status() -> MoveClusterUndoStatusResponse:
    return MoveClusterUndoStatusResponse(**adata_service.get_latest_move_status())


@router.post("/move-cluster-undo", response_model=MoveClusterUndoResponse)
def undo_move_cluster() -> MoveClusterUndoResponse:
    try:
        payload = adata_service.undo_latest_move()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    registry.scan(registry.scan_root or settings.default_lineage_root)
    return MoveClusterUndoResponse(**payload)


@router.get("/object-change-undo", response_model=ObjectChangeUndoStatusResponse)
def object_change_undo_status() -> ObjectChangeUndoStatusResponse:
    return ObjectChangeUndoStatusResponse(**adata_service.get_latest_object_change_status())


@router.post("/object-change-undo", response_model=ObjectChangeUndoResponse)
def undo_object_change() -> ObjectChangeUndoResponse:
    try:
        payload = adata_service.undo_latest_object_change()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    registry.scan(registry.scan_root or settings.default_lineage_root)
    return ObjectChangeUndoResponse(**payload)


# ── F-04 / F-13  Obs metadata coloring & QC ──────────────────────────────────

@router.get("/objects/{object_id}/obs-columns", response_model=ObsColumnsResponse)
def object_obs_columns(object_id: str) -> ObsColumnsResponse:
    record = _resolve_record(object_id)
    payload = adata_service.get_obs_columns(record)
    return ObsColumnsResponse(**payload)


@router.post("/objects/{object_id}/obs-values", response_model=ObsValuesResponse)
def object_obs_values(object_id: str, request: ObsValuesRequest) -> ObsValuesResponse:
    record = _resolve_record(object_id)
    try:
        payload = adata_service.get_obs_values(record, request.column, request.indices)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ObsValuesResponse(**payload)


@router.get("/global/obs-columns", response_model=ObsColumnsResponse)
def global_obs_columns() -> ObsColumnsResponse:
    record = _global_record()
    payload = adata_service.get_obs_columns(record)
    return ObsColumnsResponse(**payload)


@router.post("/global/obs-values", response_model=ObsValuesResponse)
def global_obs_values(request: ObsValuesRequest) -> ObsValuesResponse:
    record = _global_record()
    try:
        payload = adata_service.get_obs_values(record, request.column, request.indices)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ObsValuesResponse(**payload)


# ── F-08  Differential expression ────────────────────────────────────────────

@router.post("/objects/{object_id}/differential-expression", response_model=DEResponse)
def differential_expression(object_id: str, request: DERequest) -> DEResponse:
    record = _resolve_record(object_id)
    try:
        payload = adata_service.run_de_analysis(
            record=record,
            cluster_key=request.cluster_key,
            target_clusters=request.target_clusters,
            reference_clusters=request.reference_clusters,
            top_n=request.top_n,
            method=request.method,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return DEResponse(**payload)


# ── F-09  Annotation export ───────────────────────────────────────────────────

@router.get("/objects/{object_id}/export-annotations")
def export_annotations(
    object_id: str,
    fmt: str = Query(default="csv", pattern="^(csv|tsv|json)$"),
    session_id: str | None = Query(default=None),
) -> StreamingResponse:
    record = _resolve_record(object_id)
    session_state = None
    if session_id:
        try:
            session_state = session_store.get(session_id)
        except KeyError:
            pass
    try:
        content, mime = adata_service.export_annotations(record, session_state, fmt=fmt)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    filename = f"{record.lineage_name}_annotations.{fmt}"
    return StreamingResponse(
        iter([content]),
        media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── F-10  Project dashboard ───────────────────────────────────────────────────

@router.get("/objects/{object_id}/coverage", response_model=ObjectAnnotationCoverage)
def object_coverage(object_id: str) -> ObjectAnnotationCoverage:
    record = _resolve_record(object_id)
    payload = adata_service.get_annotation_coverage(record)
    return ObjectAnnotationCoverage(**payload)


@router.get("/dashboard", response_model=list[ObjectAnnotationCoverage])
def dashboard() -> list[ObjectAnnotationCoverage]:
    records = registry.list_records()
    return [ObjectAnnotationCoverage(**adata_service.get_annotation_coverage(r)) for r in records]


# ── F-15  Annotation diff ─────────────────────────────────────────────────────

@router.post("/objects/{object_id}/annotation-diff", response_model=AnnotationDiffResponse)
def annotation_diff(object_id: str, request: AnnotationDiffRequest) -> AnnotationDiffResponse:
    record = _resolve_record(object_id)
    try:
        payload = adata_service.compare_cluster_columns(record, request.key_a, request.key_b)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AnnotationDiffResponse(**payload)


# ── F-03  Persistent session recovery ────────────────────────────────────────

@router.get("/objects/{object_id}/live-session", response_model=LiveSessionResponse)
def live_session_status(object_id: str) -> LiveSessionResponse:
    record = _resolve_record(object_id)
    summary = session_store.live_session_summary(record.lineage_dir, object_id)
    return LiveSessionResponse(**summary)


@router.post("/objects/{object_id}/restore-live-session", response_model=SessionSummaryResponse)
def restore_live_session(object_id: str) -> SessionSummaryResponse:
    record = _resolve_record(object_id)
    session = session_store.restore_live(record.lineage_dir, object_id)
    if session is None:
        raise HTTPException(status_code=404, detail="No live session found for this object.")
    return SessionSummaryResponse(**session_store.summarize(session.session_id))


@router.delete("/objects/{object_id}/live-session")
def clear_live_session(object_id: str) -> dict[str, str]:
    record = _resolve_record(object_id)
    session_store.clear_live(record.lineage_dir, object_id)
    return {"status": "cleared", "object_id": object_id}
