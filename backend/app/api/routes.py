from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import anndata as ad
import h5py
import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException

from app.core.config import settings
from app.models.state import PolygonSeedBatch, PropagationSnapshot
from app.schemas.api import (
    ClusterLabelEditorResponse,
    DotplotRequest,
    DotplotResponse,
    GeneCatalogResponse,
    GeneExpressionRequest,
    GeneExpressionResponse,
    HighlightGlobalRequest,
    MarkerDiscoveryRequest,
    MarkerDiscoveryResponse,
    MetadataResponse,
    MoveClusterRequest,
    MoveClusterPreviewResponse,
    MoveClusterResponse,
    MoveClusterUndoResponse,
    MoveClusterUndoStatusResponse,
    ObjectCard,
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
    build_knn_graph,
    neighborhood_mask,
    run_graph_diffusion,
    run_knn_vote,
)
from app.services.registry import registry
from app.services.sessions import session_store

router = APIRouter()


def _json_safe(value):
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.ndarray):
        return [_json_safe(item) for item in value.tolist()]
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    return value


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


def _string_series(values, index) -> pd.Series:
    return pd.Series(np.asarray(values, dtype=object), index=index, dtype=object)


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


@router.post("/scan-folder", response_model=list[ObjectCard])
def scan_folder(request: ScanFolderRequest) -> list[ObjectCard]:
    fallback_folder = settings.default_lineage_root
    requested_folder = Path(request.folder_path).expanduser() if request.folder_path else None
    if requested_folder and not requested_folder.exists() and str(requested_folder) == "/data/lineages_current":
        folder = fallback_folder
    else:
        folder = requested_folder or fallback_folder
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
def global_umap(request: UmapRequest) -> UmapResponse:
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
        payload = adata_service.get_gene_expression_values(record, request.gene_name, request.indices)
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
        payload = adata_service.get_gene_expression_values(record, request.gene_name, request.indices)
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
def umap_points(object_id: str, request: UmapRequest) -> UmapResponse:
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

    adata = adata_service.get_adata(record)
    n_obs = adata.n_obs
    seed_labels = np.full(n_obs, "", dtype=object)
    for index, label in session.seed_labels.items():
        seed_labels[index] = label
    seed_mask = seed_labels != ""
    if not seed_mask.any():
        raise HTTPException(status_code=400, detail="No seed cells available in the session.")

    cluster_values = (
        adata.obs[request.cluster_key].astype("string").fillna("NA").to_numpy(dtype=object)
        if request.cluster_key in adata.obs.columns
        else np.full(n_obs, "all", dtype=object)
    )
    graph = adata_service.get_graph(record)
    eligible_mask = _eligible_mask(
        request.scope,
        graph,
        seed_mask,
        cluster_values,
        neighborhood_hops=request.neighborhood_hops,
    )

    if graph is None:
        graph = build_knn_graph(adata_service.get_features(record), request.n_neighbors)
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
        cell_id = str(adata.obs.iloc[idx]["cell_id"]) if "cell_id" in adata.obs.columns else str(adata.obs_names[idx])
        cells.append(
            {
                "index": int(idx),
                "obs_name": str(adata.obs_names[idx]),
                "cell_id": cell_id,
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
    if session.last_propagation is None:
        raise HTTPException(status_code=400, detail="No propagated result is available to save.")

    adata = adata_service.get_adata(record).copy()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = record.object_path

    n_obs = adata.n_obs
    seed_mask = np.zeros(n_obs, dtype=bool)
    seed_label_values = np.full(n_obs, "", dtype=object)
    polygon_ids = np.full(n_obs, "", dtype=object)
    for index, label in session.seed_labels.items():
        seed_mask[index] = True
        seed_label_values[index] = label
        polygon_ids[index] = ";".join(sorted(session.seed_polygon_ids.get(index, set())))

    result = session.last_propagation
    label_definitions = dict(session.seed_display_names)
    display_labels = np.asarray(
        [label_definitions.get(str(label), str(label)) for label in result.assigned_labels],
        dtype=object,
    )
    adata.obs["reannot_label"] = _string_series(result.assigned_labels, adata.obs_names)
    adata.obs["reannot_display_label"] = _string_series(display_labels, adata.obs_names)
    adata.obs["reannot_label_source"] = _string_series(
        np.where(seed_mask, "polygon_seed", np.where(result.assigned_mask, result.method, "unassigned")),
        adata.obs_names,
    )
    adata.obs["reannot_confidence"] = pd.Series(result.assigned_scores, index=adata.obs_names, dtype=float)
    adata.obs["reannot_margin"] = pd.Series(result.assigned_margins, index=adata.obs_names, dtype=float)
    adata.obs["reannot_seed"] = pd.Series(seed_mask, index=adata.obs_names, dtype=bool)
    adata.obs["reannot_polygon_ids"] = _string_series(polygon_ids, adata.obs_names)
    adata.obs["reannot_scope"] = _string_series(np.repeat(result.scope, n_obs), adata.obs_names)
    adata.obs["reannot_cluster_key"] = _string_series(np.repeat(result.cluster_key, n_obs), adata.obs_names)
    adata.obs["reannot_session_id"] = _string_series(np.repeat(session.session_id, n_obs), adata.obs_names)
    adata.obs["reannot_timestamp"] = _string_series(np.repeat(timestamp, n_obs), adata.obs_names)

    save_manifest = {
        "session_id": session.session_id,
        "source_object": str(record.object_path),
        "saved_object": str(output_path),
        "embedding_key": session.embedding_key,
        "cluster_key": session.cluster_key,
        "method": result.method,
        "scope": result.scope,
        "annotate_all": result.annotate_all,
        "graph_smoothing": result.graph_smoothing,
        "n_seed_cells": int(seed_mask.sum()),
        "n_assigned_cells": int(result.assigned_mask.sum()),
        "timestamp": timestamp,
    }
    existing_history = adata.uns.get("reannotation_sessions", {})
    if isinstance(existing_history, list):
        sessions_history = {
            str(index): value
            for index, value in enumerate(existing_history)
            if isinstance(value, dict)
        }
    elif isinstance(existing_history, dict):
        sessions_history = dict(existing_history)
    else:
        sessions_history = {}
    sessions_history[timestamp] = save_manifest
    sessions_history_safe = _json_safe(sessions_history)
    save_manifest_safe = _json_safe(save_manifest)
    label_definitions_safe = _json_safe(label_definitions)
    adata.uns["reannotation_sessions"] = sessions_history_safe
    adata.uns["reannotation_sessions_json"] = json.dumps(sessions_history_safe, indent=2)
    adata.uns["reannotation_last_session"] = save_manifest_safe
    adata.uns["reannotation_label_definitions"] = label_definitions_safe
    adata.uns["reannotation_save_manifest"] = save_manifest_safe

    adata_service._write_object(record, adata, prefix=f"{record.object_path.stem}_save_")
    cluster_series = (
        adata.obs[result.cluster_key].astype("string").fillna("NA")
        if result.cluster_key in adata.obs.columns
        else pd.Series("all", index=adata.obs_names, dtype="string")
    )
    frame = pd.DataFrame(
        {
            "cluster": cluster_series.to_numpy(dtype=object),
            "predicted_label": result.assigned_labels,
            "assigned": result.assigned_mask,
            "score": result.assigned_scores,
        }
    )
    cluster_summary = []
    for cluster, group in frame.groupby("cluster", sort=True):
        if bool(group["assigned"].any()):
            label_counts = group.loc[group["assigned"], "predicted_label"].value_counts(normalize=True)
            predicted_label = str(label_counts.index[0])
            purity = float(label_counts.iloc[0])
        else:
            predicted_label = "Unassigned"
            purity = 0.0
        cluster_summary.append(
            {
                "cluster": str(cluster),
                "predicted_label": predicted_label,
                "n_cells": int(group.shape[0]),
                "n_assigned": int(group["assigned"].sum()),
                "purity": purity,
                "mean_score": float(group["score"].mean()),
            }
        )
    session_json_path, polygons_geojson_path, summary_csv_path = session_store.save_sidecars(
        session_id=session.session_id,
        base_path=record.object_path.with_suffix(""),
        cluster_summary=cluster_summary,
    )

    return SaveResponse(
        object_path=str(record.object_path),
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
