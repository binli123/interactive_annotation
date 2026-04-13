from __future__ import annotations

import base64
import io
import json
import os
import re
import shutil
from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import anndata as ad
import h5py
import numpy as np
import pandas as pd
from scipy import sparse
from sklearn.neighbors import KNeighborsClassifier

from app.core.config import settings
from app.models.state import ObjectRecord
from app.services.polygon_ops import points_in_polygon
from app.services.registry import registry
from app.services.sampling import priority_stratified_sample_indices, stratified_sample_indices


def _obs_to_str_array(frame: pd.DataFrame, column: str, default: str = "") -> np.ndarray:
    if column not in frame.columns:
        return np.full(frame.shape[0], default, dtype=object)
    series = frame[column].astype("string").fillna(default)
    return series.to_numpy(dtype=object)


def _obs_to_float_array(frame: pd.DataFrame, column: str) -> np.ndarray | None:
    if column not in frame.columns:
        return None
    return pd.to_numeric(frame[column], errors="coerce").to_numpy(dtype=float)


def _display_column_name(cluster_key: str) -> str:
    if cluster_key == "reannot_label":
        return "reannot_display_label"
    if cluster_key.startswith("reannot_label_"):
        return cluster_key.replace("reannot_label_", "reannot_display_label_", 1)
    if cluster_key.endswith("_label"):
        return f"{cluster_key[:-6]}_display_label"
    return f"{cluster_key}_display_name"


def _sanitize_suffix(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in value.strip().lower())
    cleaned = "_".join(part for part in cleaned.split("_") if part)
    return cleaned or "new"


def _next_available_cluster_id(existing_ids: list[str], requested_id: str) -> str:
    existing = {str(value) for value in existing_ids}
    numeric_values = []
    for value in existing:
        if re.fullmatch(r"-?\d+", value):
            numeric_values.append(int(value))

    if numeric_values:
        candidate = max(numeric_values) + 1
        while str(candidate) in existing:
            candidate += 1
        return str(candidate)

    if requested_id not in existing:
        return requested_id

    suffix = 1
    candidate = f"{requested_id}_moved_{suffix}"
    while candidate in existing:
        suffix += 1
        candidate = f"{requested_id}_moved_{suffix}"
    return candidate


def _coerce_series_for_union(frame: pd.DataFrame, column: str) -> pd.Series:
    series = frame[column]
    if pd.api.types.is_bool_dtype(series):
        return series.astype("boolean")
    if pd.api.types.is_numeric_dtype(series):
        return pd.to_numeric(series, errors="coerce")
    return series.astype("string")


def _strip_origin_suffix(value: str) -> str:
    return re.sub(r"\s+\(from .+\)$", "", value).strip()


def _normalize_series_for_write(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.astype("boolean")
    if pd.api.types.is_numeric_dtype(series):
        return pd.to_numeric(series, errors="coerce")

    non_null = series.dropna()
    if not non_null.empty:
        numeric_probe = pd.to_numeric(non_null.astype(str), errors="coerce")
        if not numeric_probe.isna().any():
            numeric_full = pd.to_numeric(series.astype("string"), errors="coerce")
            if (numeric_probe % 1 == 0).all():
                return numeric_full.astype("Int64")
            return numeric_full.astype(float)

    return series.astype("string")


def _normalize_obs_for_write(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = frame.copy()
    for column in normalized.columns:
        normalized[column] = _normalize_series_for_write(normalized[column])
    return normalized


def _python_scalar(value: Any) -> Any:
    if isinstance(value, np.generic):
        return value.item()
    return value


def _bool_value(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    return bool(_python_scalar(value))


def _unique_obs_names(incoming_names: pd.Index, existing_names: pd.Index) -> pd.Index:
    used = {str(value) for value in existing_names.tolist()}
    assigned: list[str] = []
    for raw_name in incoming_names.tolist():
        base = str(raw_name)
        candidate = base
        suffix = 1
        while candidate in used:
            candidate = f"{base}_moved_{suffix}"
            suffix += 1
        used.add(candidate)
        assigned.append(candidate)
    return pd.Index(assigned)


def _write_safe_plot_env() -> dict[str, Path]:
    numba_cache = settings.project_root / ".numba_cache"
    mpl_cache = settings.project_root / ".mplconfig"
    xdg_cache = settings.project_root / ".cache"
    fontconfig_cache = xdg_cache / "fontconfig"
    numba_cache.mkdir(parents=True, exist_ok=True)
    mpl_cache.mkdir(parents=True, exist_ok=True)
    fontconfig_cache.mkdir(parents=True, exist_ok=True)
    os.environ["NUMBA_CACHE_DIR"] = str(numba_cache)
    os.environ["MPLCONFIGDIR"] = str(mpl_cache)
    os.environ["XDG_CACHE_HOME"] = str(xdg_cache)
    return {
        "numba_cache": numba_cache,
        "mpl_cache": mpl_cache,
        "xdg_cache": xdg_cache,
    }


def _cluster_key_candidates(frame: pd.DataFrame) -> list[str]:
    excluded = {
        "_index",
        "cell_id",
        "sample_id",
        "region",
        "run_id",
        "original_id",
        "cell_index",
        "segmentation_method",
        "z_level",
    }
    preferred = [
        "reannot_display_label",
        "reannot_label",
        "final_substate_refined",
        "round2_substate",
        "round1_auto_substate",
        "celltypist_prediction",
        "final_valid_lineage",
        "lineage",
    ]
    candidates: list[str] = []
    for column in frame.columns:
        if column in excluded:
            continue
        series = frame[column]
        if column.startswith("leiden_"):
            candidates.append(column)
            continue
        if column in preferred:
            candidates.append(column)
            continue
        if not (
            pd.api.types.is_string_dtype(series)
            or pd.api.types.is_categorical_dtype(series)
            or pd.api.types.is_object_dtype(series)
        ):
            continue
        non_null = series.dropna()
        if non_null.empty:
            continue
        n_unique = int(non_null.astype("string").nunique())
        if 2 <= n_unique <= 256:
            candidates.append(column)

    ordered: list[str] = []
    seen: set[str] = set()
    for column in preferred + sorted(candidates):
        if column in frame.columns and column not in seen:
            ordered.append(column)
            seen.add(column)
    return ordered


class AnnDataService:
    def __init__(self, max_cached_objects: int = settings.max_cached_objects) -> None:
        self.max_cached_objects = max_cached_objects
        self._cache: OrderedDict[str, ad.AnnData] = OrderedDict()
        self._cell_id_cache: dict[str, np.ndarray] = {}

    def _touch(self, object_id: str, adata: ad.AnnData) -> ad.AnnData:
        self._cache[object_id] = adata
        self._cache.move_to_end(object_id)
        while len(self._cache) > self.max_cached_objects:
            evicted_object_id, evicted = self._cache.popitem(last=False)
            self._cell_id_cache.pop(evicted_object_id, None)
            if getattr(evicted, "isbacked", False):
                evicted.file.close()
        return adata

    def replace_cached(self, object_id: str, adata: ad.AnnData) -> ad.AnnData:
        cached = self._cache.pop(object_id, None)
        if cached is not None and getattr(cached, "isbacked", False):
            cached.file.close()
        self._cell_id_cache.pop(object_id, None)
        return self._touch(object_id, adata)

    def get_adata(self, record: ObjectRecord) -> ad.AnnData:
        cached = self._cache.get(record.object_id)
        if cached is not None:
            self._cache.move_to_end(record.object_id)
            return cached
        try:
            adata = ad.read_h5ad(record.object_path)
        except Exception as exc:
            raise ValueError(
                f"Object is not a readable AnnData file for interactive viewing: {record.object_path}. "
                "It is likely missing required groups such as var/obsm."
            ) from exc
        return self._touch(record.object_id, adata)

    def invalidate_cached(self, object_id: str) -> None:
        cached = self._cache.pop(object_id, None)
        if cached is not None and getattr(cached, "isbacked", False):
            cached.file.close()
        self._cell_id_cache.pop(object_id, None)

    def _get_cell_ids(self, record: ObjectRecord) -> np.ndarray:
        cached = self._cell_id_cache.get(record.object_id)
        if cached is not None:
            return cached
        adata = self.get_adata(record)
        if "cell_id" in adata.obs.columns:
            cell_ids = _obs_to_str_array(adata.obs, "cell_id")
        else:
            cell_ids = adata.obs_names.to_numpy(dtype=object)
        normalized = np.asarray(cell_ids, dtype=object).astype(str, copy=False)
        self._cell_id_cache[record.object_id] = normalized
        return normalized

    def _move_undo_dir(self) -> Path:
        path = settings.project_root / ".move_undo"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _move_undo_metadata_path(self) -> Path:
        return self._move_undo_dir() / "latest_move.json"

    def _move_undo_source_path(self) -> Path:
        return self._move_undo_dir() / "latest_source_before_move.h5ad"

    def _move_undo_destination_path(self) -> Path:
        return self._move_undo_dir() / "latest_destination_before_move.h5ad"

    def _clear_latest_move_snapshot(self) -> None:
        for path in (
            self._move_undo_metadata_path(),
            self._move_undo_source_path(),
            self._move_undo_destination_path(),
        ):
            path.unlink(missing_ok=True)

    def _latest_move_status_payload(self) -> dict[str, Any]:
        metadata_path = self._move_undo_metadata_path()
        if not metadata_path.exists():
            return {"available": False}
        try:
            payload = json.loads(metadata_path.read_text())
        except Exception:
            self._clear_latest_move_snapshot()
            return {"available": False}

        source_snapshot_path = Path(payload.get("source_snapshot_path", ""))
        destination_snapshot_path = Path(payload.get("destination_snapshot_path", ""))
        if not source_snapshot_path.exists() or not destination_snapshot_path.exists():
            self._clear_latest_move_snapshot()
            return {"available": False}

        return {"available": True, **payload}

    def get_latest_move_status(self) -> dict[str, Any]:
        return self._latest_move_status_payload()

    def _record_latest_move_snapshot(
        self,
        *,
        source_record: ObjectRecord,
        destination_record: ObjectRecord,
        preview: dict[str, Any],
    ) -> None:
        self._clear_latest_move_snapshot()
        source_snapshot_path = self._move_undo_source_path()
        destination_snapshot_path = self._move_undo_destination_path()
        shutil.copy2(source_record.object_path, source_snapshot_path)
        try:
            shutil.copy2(destination_record.object_path, destination_snapshot_path)
        except Exception:
            source_snapshot_path.unlink(missing_ok=True)
            raise

        payload = {
            "source_object_id": source_record.object_id,
            "source_object_path": str(source_record.object_path),
            "source_lineage_name": source_record.lineage_name,
            "destination_object_id": destination_record.object_id,
            "destination_object_path": str(destination_record.object_path),
            "destination_lineage_name": destination_record.lineage_name,
            "cluster_key": str(preview["cluster_key"]),
            "source_cluster_id": str(preview["source_cluster_id"]),
            "assigned_cluster_id": str(preview["assigned_cluster_id"]),
            "display_name": str(preview["display_name"]),
            "n_moved_cells": int(preview["n_moved_cells"]),
            "n_overwritten_cells": int(preview["n_overwritten_cells"]),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_snapshot_path": str(source_snapshot_path),
            "destination_snapshot_path": str(destination_snapshot_path),
        }
        self._move_undo_metadata_path().write_text(json.dumps(payload, indent=2))

    def undo_latest_move(self) -> dict[str, Any]:
        payload = self._latest_move_status_payload()
        if not payload.get("available"):
            raise ValueError("No move snapshot is available to undo.")

        source_record = registry.build_record(
            object_path=Path(str(payload["source_object_path"])),
            lineage_name=str(payload.get("source_lineage_name") or Path(str(payload["source_object_path"])).stem),
            lineage_dir=Path(str(payload["source_object_path"])).parent,
        )
        destination_record = registry.build_record(
            object_path=Path(str(payload["destination_object_path"])),
            lineage_name=str(payload.get("destination_lineage_name") or Path(str(payload["destination_object_path"])).stem),
            lineage_dir=Path(str(payload["destination_object_path"])).parent,
        )

        source_snapshot_path = Path(str(payload["source_snapshot_path"]))
        destination_snapshot_path = Path(str(payload["destination_snapshot_path"]))
        if not source_snapshot_path.exists() or not destination_snapshot_path.exists():
            self._clear_latest_move_snapshot()
            raise ValueError("The saved move snapshot is incomplete and cannot be restored.")

        source_restore_path = source_record.object_path.with_suffix(source_record.object_path.suffix + ".undo_restore")
        destination_restore_path = destination_record.object_path.with_suffix(destination_record.object_path.suffix + ".undo_restore")
        shutil.copy2(source_snapshot_path, source_restore_path)
        try:
            shutil.copy2(destination_snapshot_path, destination_restore_path)
        except Exception:
            source_restore_path.unlink(missing_ok=True)
            raise

        try:
            source_restore_path.replace(source_record.object_path)
            destination_restore_path.replace(destination_record.object_path)
        except Exception:
            source_restore_path.unlink(missing_ok=True)
            destination_restore_path.unlink(missing_ok=True)
            raise

        self.invalidate_cached(source_record.object_id)
        self.invalidate_cached(destination_record.object_id)
        self._clear_latest_move_snapshot()

        return {
            "available": False,
            "restored": True,
            "source_object_id": source_record.object_id,
            "source_object_path": str(source_record.object_path),
            "destination_object_id": destination_record.object_id,
            "destination_object_path": str(destination_record.object_path),
            "cluster_key": str(payload["cluster_key"]),
            "source_cluster_id": str(payload["source_cluster_id"]),
            "assigned_cluster_id": str(payload["assigned_cluster_id"]),
            "display_name": str(payload["display_name"]),
            "n_moved_cells": int(payload["n_moved_cells"]),
            "n_overwritten_cells": int(payload["n_overwritten_cells"]),
            "created_at": str(payload["created_at"]),
        }

    def _embedding_recompute_config(self, adata: ad.AnnData) -> dict[str, Any]:
        script_info = {
            str(key): _python_scalar(value)
            for key, value in dict(adata.uns.get("recomputed_umap_all_genes", {})).items()
        }
        neighbors_params = {
            str(key): _python_scalar(value)
            for key, value in dict(adata.uns.get("neighbors", {}).get("params", {})).items()
        }
        pca_params = {
            str(key): _python_scalar(value)
            for key, value in dict(adata.uns.get("pca", {}).get("params", {})).items()
        }
        umap_params = {
            str(key): _python_scalar(value)
            for key, value in dict(adata.uns.get("umap", {}).get("params", {})).items()
        }

        n_obs = int(adata.n_obs)
        n_vars = int(adata.n_vars)
        max_components = max(2, min(50, n_obs - 1, n_vars))
        configured_pcs = int(script_info.get("n_pcs") or neighbors_params.get("n_pcs") or 50)
        n_pcs = max(2, min(configured_pcs, max_components))
        configured_neighbors = int(script_info.get("n_neighbors") or neighbors_params.get("n_neighbors") or settings.default_neighbors)
        n_neighbors = max(2, min(configured_neighbors, max(2, n_obs - 1)))

        x_sample = adata.X[: min(n_obs, 2048)]
        if sparse.issparse(x_sample):
            nonzero = x_sample.data
        else:
            x_array = np.asarray(x_sample)
            nonzero = x_array[x_array > 0]
        max_nonzero = float(nonzero.max()) if nonzero.size else 0.0
        non_integer_fraction = (
            float(np.mean(~np.isclose(nonzero, np.round(nonzero)))) if nonzero.size else 0.0
        )
        looks_logged = max_nonzero <= 25.0 and non_integer_fraction > 0.05

        return {
            "n_pcs": n_pcs,
            "n_neighbors": n_neighbors,
            "metric": str(script_info.get("metric") or neighbors_params.get("metric") or "cosine"),
            "random_state": int(script_info.get("random_state") or neighbors_params.get("random_state") or 0),
            "min_dist": float(script_info.get("min_dist") or umap_params.get("min_dist") or 0.3),
            "spread": float(script_info.get("spread") or umap_params.get("spread") or 1.0),
            "zero_center": _bool_value(pca_params.get("zero_center"), default=False),
            "use_highly_variable": _bool_value(pca_params.get("use_highly_variable"), default=False),
            "normalize_first": _bool_value(script_info.get("normalized_in_script"), default=not looks_logged),
            "log1p_first": _bool_value(script_info.get("log1p_in_script"), default=not looks_logged),
            "input_already_logged": _bool_value(script_info.get("input_already_logged"), default=looks_logged),
            "max_nonzero": max_nonzero,
            "non_integer_fraction": non_integer_fraction,
        }

    def recompute_embeddings(self, adata: ad.AnnData, context_label: str) -> ad.AnnData:
        if adata.n_obs == 0:
            raise ValueError(f"Cannot recompute embeddings for empty object: {context_label}")

        config = self._embedding_recompute_config(adata)
        if adata.n_obs < 3 or adata.n_vars < 2:
            x_pca = np.zeros((adata.n_obs, min(2, max(1, adata.n_vars))), dtype=np.float32)
            x_umap = np.zeros((adata.n_obs, 2), dtype=np.float32)
            adata.obsm["X_pca"] = x_pca
            adata.obsm["X_umap"] = x_umap
            adata.uns["neighbors"] = {"params": {"method": "insufficient_cells"}}
            adata.uns["pca"] = {"params": {"zero_center": False}}
            adata.uns["umap"] = {"params": {"min_dist": 0.0}}
            adata.obsp.clear()
            return adata

        env_paths = _write_safe_plot_env()
        import numba

        numba.config.CACHE_DIR = str(env_paths["numba_cache"])
        import scanpy as sc

        if config["normalize_first"] and not config["input_already_logged"]:
            sc.pp.normalize_total(adata, target_sum=1e4)
        if config["log1p_first"] and not config["input_already_logged"]:
            sc.pp.log1p(adata)

        sc.pp.pca(
            adata,
            n_comps=int(config["n_pcs"]),
            zero_center=bool(config["zero_center"]),
            use_highly_variable=bool(config["use_highly_variable"]),
        )
        sc.pp.neighbors(
            adata,
            n_neighbors=int(config["n_neighbors"]),
            n_pcs=int(config["n_pcs"]),
            use_rep="X_pca",
            metric=str(config["metric"]),
        )
        sc.tl.umap(
            adata,
            min_dist=float(config["min_dist"]),
            spread=float(config["spread"]),
            random_state=int(config["random_state"]),
        )

        adata.uns["move_cluster_recompute"] = {
            "context_label": context_label,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "n_neighbors": int(config["n_neighbors"]),
            "n_pcs": int(config["n_pcs"]),
            "metric": str(config["metric"]),
            "min_dist": float(config["min_dist"]),
            "spread": float(config["spread"]),
            "normalize_first": bool(config["normalize_first"] and not config["input_already_logged"]),
            "log1p_first": bool(config["log1p_first"] and not config["input_already_logged"]),
            "input_already_logged": bool(config["input_already_logged"]),
            "matrix_check_max_nonzero": float(config["max_nonzero"]),
            "matrix_check_frac_non_integer": float(config["non_integer_fraction"]),
        }
        return adata

    def get_metadata(self, record: ObjectRecord) -> dict[str, Any]:
        adata = self.get_adata(record)
        embedding_keys = sorted(list(adata.obsm.keys()))
        if not embedding_keys:
            raise ValueError(
                f"Object has no embeddings available for viewing: {record.object_path}. "
                "Use a lineage object with saved UMAP coordinates."
            )
        cluster_keys = _cluster_key_candidates(adata.obs)
        pca_keys = [key for key in embedding_keys if "pca" in key.lower()]
        if "X_umap" in embedding_keys:
            default_embedding = "X_umap"
        elif "X_umap_lineage" in embedding_keys:
            default_embedding = "X_umap_lineage"
        else:
            default_embedding = embedding_keys[0]
        default_cluster = next((key for key in ("reannot_label", "reannot_display_label") if key in cluster_keys), None)
        if default_cluster is None and record.lineage_name == "Global" and "final_valid_lineage" in cluster_keys:
            default_cluster = "final_valid_lineage"
        if default_cluster is None:
            default_cluster = cluster_keys[0] if cluster_keys else None
        return {
            "object_id": record.object_id,
            "lineage_name": record.lineage_name,
            "object_path": str(record.object_path),
            "shape": (int(adata.n_obs), int(adata.n_vars)),
            "cluster_keys": cluster_keys,
            "embedding_keys": embedding_keys,
            "pca_keys": pca_keys,
            "default_embedding_key": default_embedding,
            "default_cluster_key": default_cluster,
            "has_connectivities": "lineage_connectivities" in adata.obsp,
            "has_distances": "lineage_distances" in adata.obsp,
            "summary_resolution_trials": record.resolution_trials,
            "obs_columns": list(adata.obs.columns),
            "sample_columns": [col for col in ("sample_id", "region", "lineage", "final_valid_lineage") if col in adata.obs.columns],
            "manifest": record.manifest,
        }

    def _point_payload(
        self,
        adata: ad.AnnData,
        record: ObjectRecord,
        indices: np.ndarray,
        coords: np.ndarray,
        clusters: np.ndarray,
        gene_name: str | None,
        highlight_mask: np.ndarray | None = None,
    ) -> dict[str, Any]:
        obs_frame = adata.obs.iloc[indices]
        cell_ids = self._get_cell_ids(record)[indices]

        label_column = next(
            (
                column
                for column in ("reannot_display_label", "reannot_label", "current_label", "celltypist_label")
                if column in adata.obs.columns
            ),
            None,
        )
        score_column = next(
            (column for column in ("reannot_confidence", "current_score", "celltypist_confidence") if column in adata.obs.columns),
            None,
        )
        current_label = (
            _obs_to_str_array(adata.obs, label_column)[indices]
            if label_column
            else np.full(indices.size, "", dtype=object)
        )
        current_score = (
            _obs_to_float_array(adata.obs, score_column)[indices]
            if score_column
            else np.full(indices.size, np.nan, dtype=float)
        )
        gene_expression = (
            self._extract_gene_expression(adata, gene_name, indices)
            if gene_name
            else np.full(indices.size, np.nan, dtype=float)
        )

        points = []
        for local_pos, obs_index in enumerate(indices.tolist()):
            point = {
                "index": int(obs_index),
                "obs_name": str(adata.obs_names[obs_index]),
                "cell_id": str(cell_ids[local_pos]),
                "x": float(coords[obs_index, 0]),
                "y": float(coords[obs_index, 1]),
                "cluster": str(clusters[obs_index]),
                "sample_id": str(obs_frame.iloc[local_pos]["sample_id"]) if "sample_id" in obs_frame.columns else None,
                "region": str(obs_frame.iloc[local_pos]["region"]) if "region" in obs_frame.columns else None,
                "lineage": str(obs_frame.iloc[local_pos]["lineage"]) if "lineage" in obs_frame.columns else None,
                "current_label": str(current_label[local_pos]) if current_label[local_pos] else None,
                "current_score": None if np.isnan(current_score[local_pos]) else float(current_score[local_pos]),
                "gene_expression": None if np.isnan(gene_expression[local_pos]) else float(gene_expression[local_pos]),
            }
            if highlight_mask is not None:
                point["is_highlighted"] = bool(highlight_mask[obs_index])
            points.append(point)

        response: dict[str, Any] = {
            "object_id": record.object_id,
            "points": points,
        }
        if highlight_mask is not None:
            displayed_highlight = highlight_mask[indices]
            response["highlighted_total"] = int(highlight_mask.sum())
            response["highlighted_displayed"] = int(displayed_highlight.sum())
        return response

    def get_umap_points(
        self,
        record: ObjectRecord,
        embedding_key: str,
        cluster_key: str | None,
        gene_name: str | None,
        max_points: int,
        min_per_cluster: int,
        max_per_cluster: int,
        random_seed: int,
    ) -> dict[str, Any]:
        adata = self.get_adata(record)
        coords = np.asarray(adata.obsm[embedding_key])[:, :2]
        clusters = (
            _obs_to_str_array(adata.obs, cluster_key, default="all")
            if cluster_key
            else np.full(adata.n_obs, "all", dtype=object)
        )
        indices = stratified_sample_indices(
            labels=clusters.astype(str),
            max_points=max_points,
            min_per_cluster=min_per_cluster,
            max_per_cluster=max_per_cluster if max_per_cluster > 0 else None,
            random_seed=random_seed,
        )
        payload = self._point_payload(
            adata=adata,
            record=record,
            indices=indices,
            coords=coords,
            clusters=clusters,
            gene_name=gene_name,
        )

        return {
            **payload,
            "embedding_key": embedding_key,
            "cluster_key": cluster_key,
            "gene_name": gene_name,
            "total_cells": int(adata.n_obs),
            "displayed_cells": int(indices.size),
            "points": payload["points"],
        }

    def get_umap_points_with_highlight(
        self,
        record: ObjectRecord,
        embedding_key: str,
        cluster_key: str | None,
        highlight_cell_ids: set[str],
        max_points: int,
        min_per_cluster: int,
        max_per_cluster: int,
        random_seed: int,
    ) -> dict[str, Any]:
        adata = self.get_adata(record)
        coords = np.asarray(adata.obsm[embedding_key])[:, :2]
        clusters = (
            _obs_to_str_array(adata.obs, cluster_key, default="all")
            if cluster_key
            else np.full(adata.n_obs, "all", dtype=object)
        )
        cell_ids = self._get_cell_ids(record)
        highlight_mask = np.isin(cell_ids, list(highlight_cell_ids))
        indices = priority_stratified_sample_indices(
            labels=clusters.astype(str),
            priority_mask=highlight_mask,
            max_points=max_points,
            min_per_cluster=min_per_cluster,
            max_per_cluster=max_per_cluster if max_per_cluster > 0 else None,
            random_seed=random_seed,
        )
        payload = self._point_payload(
            adata=adata,
            record=record,
            indices=indices,
            coords=coords,
            clusters=clusters,
            gene_name=None,
            highlight_mask=highlight_mask,
        )
        return {
            **payload,
            "embedding_key": embedding_key,
            "cluster_key": cluster_key,
            "gene_name": None,
            "total_cells": int(adata.n_obs),
            "displayed_cells": int(indices.size),
            "points": payload["points"],
            "highlighted_total": payload["highlighted_total"],
            "highlighted_displayed": payload["highlighted_displayed"],
        }

    def get_gene_catalog(self, record: ObjectRecord) -> dict[str, Any]:
        adata = self.get_adata(record)
        return {
            "object_id": record.object_id,
            "object_path": str(record.object_path),
            "genes": [str(gene) for gene in adata.var_names.tolist()],
        }

    def _display_mapping(self, adata: ad.AnnData, cluster_key: str) -> dict[str, str]:
        cluster_values = _obs_to_str_array(adata.obs, cluster_key, default="NA")
        display_column = _display_column_name(cluster_key)
        if display_column in adata.obs.columns:
            display_values = _obs_to_str_array(adata.obs, display_column, default="")
        else:
            display_values = cluster_values.copy()
        mapping: dict[str, str] = {}
        for cluster_id, display_name in zip(cluster_values.tolist(), display_values.tolist(), strict=False):
            cluster_id = str(cluster_id)
            display_text = str(display_name).strip() if display_name else cluster_id
            mapping.setdefault(cluster_id, display_text or cluster_id)
        return mapping

    def _extract_gene_expression(
        self,
        adata: ad.AnnData,
        gene_name: str,
        indices: np.ndarray,
    ) -> np.ndarray:
        if gene_name not in adata.var_names:
            raise ValueError(f"Gene not found in object: {gene_name}")
        gene_index = int(adata.var_names.get_loc(gene_name))
        column = adata.X[:, gene_index]
        if sparse.issparse(column):
            values = np.asarray(column[indices].toarray()).ravel()
        else:
            values = np.asarray(column[indices]).ravel()
        return values.astype(float, copy=False)

    def get_gene_expression_values(
        self,
        record: ObjectRecord,
        gene_name: str,
        indices: list[int],
    ) -> dict[str, Any]:
        adata = self.get_adata(record)
        index_array = np.asarray(indices, dtype=int)
        if index_array.size == 0:
            return {"object_id": record.object_id, "gene_name": gene_name, "values": []}
        if int(index_array.min()) < 0 or int(index_array.max()) >= adata.n_obs:
            raise ValueError("Requested point indices are out of bounds for the current object.")
        values = self._extract_gene_expression(adata, gene_name, index_array)
        return {
            "object_id": record.object_id,
            "gene_name": gene_name,
            "values": [
                {"index": int(index), "value": float(value)}
                for index, value in zip(index_array.tolist(), values.tolist(), strict=False)
            ],
        }

    def get_point_cluster_values(
        self,
        record: ObjectRecord,
        cluster_key: str,
        indices: list[int],
    ) -> dict[str, Any]:
        adata = self.get_adata(record)
        if cluster_key not in adata.obs.columns:
            raise ValueError(f"Cluster key not found in obs: {cluster_key}")
        index_array = np.asarray(indices, dtype=int)
        if index_array.size == 0:
            return {"object_id": record.object_id, "cluster_key": cluster_key, "values": []}
        if int(index_array.min()) < 0 or int(index_array.max()) >= adata.n_obs:
            raise ValueError("Requested point indices are out of bounds for the current object.")
        cluster_values = _obs_to_str_array(adata.obs, cluster_key, default="NA")[index_array]
        return {
            "object_id": record.object_id,
            "cluster_key": cluster_key,
            "values": [
                {"index": int(index), "cluster": str(cluster)}
                for index, cluster in zip(index_array.tolist(), cluster_values.tolist(), strict=False)
            ],
        }

    def render_marker_dotplot(
        self,
        record: ObjectRecord,
        cluster_key: str,
        genes: list[str],
        save_to_object_dir: bool = False,
        output_name: str | None = None,
    ) -> dict[str, Any]:
        if not genes:
            raise ValueError("Select at least one gene for the dotplot.")

        adata = self.get_adata(record)
        if cluster_key not in adata.obs.columns:
            raise ValueError(f"Cluster key not found in obs: {cluster_key}")

        available = set(map(str, adata.var_names.tolist()))
        valid_genes = [gene for gene in genes if gene in available]
        missing_genes = [gene for gene in genes if gene not in available]
        if not valid_genes:
            raise ValueError("None of the selected genes exist in the current object.")

        display_group_key = _display_column_name(cluster_key)
        group_series = (
            adata.obs[display_group_key].astype("string").fillna("")
            if display_group_key in adata.obs.columns
            else pd.Series("", index=adata.obs_names, dtype="string")
        )
        cluster_series = adata.obs[cluster_key].astype("string").fillna("NA")
        group_values = np.where(group_series.to_numpy(dtype=object) != "", group_series.to_numpy(dtype=object), cluster_series.to_numpy(dtype=object))

        order_frame = pd.DataFrame(
            {
                "cluster": cluster_series.to_numpy(dtype=object),
                "label": group_values,
            }
        )
        ordered_labels = (
            order_frame.sort_values("cluster", kind="stable")["label"]
            .drop_duplicates()
            .astype(str)
            .tolist()
        )

        dotplot_adata = adata[:, valid_genes].copy()
        dotplot_adata.obs["__dotplot_group__"] = pd.Categorical(
            pd.Series(group_values, index=adata.obs_names, dtype="string").astype(str),
            categories=ordered_labels,
            ordered=True,
        )

        env_paths = _write_safe_plot_env()
        import numba

        numba.config.CACHE_DIR = str(env_paths["numba_cache"])
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import scanpy as sc

        dotplot = sc.pl.dotplot(
            dotplot_adata,
            var_names=valid_genes,
            groupby="__dotplot_group__",
            show=False,
            return_fig=True,
        )
        dotplot.make_figure()
        figure = dotplot.fig
        figure.set_size_inches(max(6.0, 0.45 * len(valid_genes) + 3.0), max(4.5, 0.32 * len(ordered_labels) + 2.5))
        figure.tight_layout()

        image_buffer = io.BytesIO()
        figure.savefig(image_buffer, format="png", dpi=180, bbox_inches="tight")
        image_base64 = base64.b64encode(image_buffer.getvalue()).decode("ascii")

        saved_path: str | None = None
        if save_to_object_dir:
            safe_key = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in cluster_key)
            filename = output_name or f"{record.object_path.stem}_{safe_key}_marker_dotplot.png"
            save_path = record.object_path.parent / filename
            figure.savefig(save_path, dpi=220, bbox_inches="tight")
            saved_path = str(save_path)

        plt.close(figure)

        return {
            "object_id": record.object_id,
            "object_path": str(record.object_path),
            "cluster_key": cluster_key,
            "display_group_key": display_group_key if display_group_key in adata.obs.columns else cluster_key,
            "genes": valid_genes,
            "missing_genes": missing_genes,
            "image_base64": image_base64,
            "saved_path": saved_path,
        }

    def reference_based_reannotate(
        self,
        record: ObjectRecord,
        cluster_key: str,
        reference_clusters: list[str],
        source_clusters: list[str],
        output_name: str,
        n_neighbors: int = 15,
    ) -> dict[str, Any]:
        adata = self.get_adata(record).copy()
        if cluster_key not in adata.obs.columns:
            raise ValueError(f"Cluster key not found in obs: {cluster_key}")

        cluster_values = _obs_to_str_array(adata.obs, cluster_key, default="NA")
        reference_clusters = [str(value) for value in reference_clusters]
        source_clusters = [str(value) for value in source_clusters]
        if not reference_clusters:
            raise ValueError("Select at least one reference cluster.")
        if not source_clusters:
            raise ValueError("Select at least one source cluster.")
        if set(reference_clusters) & set(source_clusters):
            raise ValueError("Reference clusters and source clusters must be disjoint.")

        reference_mask = np.isin(cluster_values.astype(str), reference_clusters)
        source_mask = np.isin(cluster_values.astype(str), source_clusters)
        if not bool(reference_mask.any()):
            raise ValueError("No cells found in the selected reference clusters.")
        if not bool(source_mask.any()):
            raise ValueError("No cells found in the selected source clusters.")

        features = self.get_features(record)
        n_neighbors = max(1, min(int(n_neighbors), int(reference_mask.sum())))
        classifier = KNeighborsClassifier(n_neighbors=n_neighbors, weights="distance")
        classifier.fit(features[reference_mask], cluster_values[reference_mask].astype(str))
        predicted = classifier.predict(features[source_mask]).astype(object)

        suffix = _sanitize_suffix(output_name)
        label_key = f"reannot_label_{suffix}"
        display_key = _display_column_name(label_key)

        new_labels = cluster_values.astype(object).copy()
        new_labels[source_mask] = predicted
        display_mapping = self._display_mapping(adata, cluster_key)
        new_display = np.asarray([display_mapping.get(str(label), str(label)) for label in new_labels], dtype=object)

        adata.obs[label_key] = pd.Series(new_labels, index=adata.obs_names, dtype=object)
        adata.obs[display_key] = pd.Series(new_display, index=adata.obs_names, dtype=object)

        definitions = deepcopy(adata.uns.get("cluster_display_name_definitions", {}))
        definitions[label_key] = {str(key): str(value) for key, value in display_mapping.items()}
        adata.uns["cluster_display_name_definitions"] = definitions

        self._write_object(record, adata, prefix=f"{record.object_path.stem}_{suffix}_refknn_")
        return {
            "object_id": record.object_id,
            "object_path": str(record.object_path),
            "source_cluster_key": cluster_key,
            "new_cluster_key": label_key,
            "display_column": display_key,
            "n_reference_cells": int(reference_mask.sum()),
            "n_source_cells": int(source_mask.sum()),
            "reference_clusters": reference_clusters,
            "source_clusters": source_clusters,
        }

    def discover_marker_genes(
        self,
        record: ObjectRecord,
        cluster_key: str,
        active_clusters: list[str],
        target_clusters: list[str],
        top_n: int,
    ) -> dict[str, Any]:
        adata = self.get_adata(record)
        if cluster_key not in adata.obs.columns:
            raise ValueError(f"Cluster key not found in obs: {cluster_key}")
        if top_n < 1:
            raise ValueError("Top N must be at least 1.")

        cluster_values = _obs_to_str_array(adata.obs, cluster_key, default="NA").astype(str)
        active_clusters = [str(value) for value in active_clusters]
        target_clusters = [str(value) for value in target_clusters]
        if not active_clusters:
            raise ValueError("At least one visible cluster is required for marker discovery.")
        if not target_clusters:
            raise ValueError("Select at least one target cluster for marker discovery.")
        if not set(target_clusters).issubset(set(active_clusters)):
            raise ValueError("Target clusters must be a subset of the active checked clusters.")

        active_mask = np.isin(cluster_values, active_clusters)
        if int(active_mask.sum()) < 3:
            raise ValueError("Not enough cells remain after restricting to checked clusters.")

        sub = adata[active_mask].copy()
        sub.obs["__marker_group__"] = pd.Categorical(
            pd.Series(cluster_values[active_mask], index=sub.obs_names, dtype="string"),
            categories=[cluster for cluster in active_clusters if cluster in set(cluster_values[active_mask])],
            ordered=True,
        )

        env_paths = _write_safe_plot_env()
        import numba

        numba.config.CACHE_DIR = str(env_paths["numba_cache"])
        import scanpy as sc

        sc.tl.rank_genes_groups(
            sub,
            groupby="__marker_group__",
            groups=target_clusters,
            reference="rest",
            method="wilcoxon",
            tie_correct=True,
            use_raw=False,
        )

        per_cluster: dict[str, list[str]] = {}
        for cluster in target_clusters:
            df = sc.get.rank_genes_groups_df(sub, group=cluster)
            if "logfoldchanges" in df.columns:
                df = df[df["logfoldchanges"].fillna(0) > 0]
            genes = [str(gene) for gene in df["names"].dropna().astype(str).tolist()]
            per_cluster[cluster] = genes

        candidates: list[str] = []
        level = 0
        while len(candidates) < top_n:
            advanced = False
            for cluster in target_clusters:
                genes = per_cluster.get(cluster, [])
                if level < len(genes):
                    gene = genes[level]
                    if gene not in candidates:
                        candidates.append(gene)
                        if len(candidates) >= top_n:
                            break
                    advanced = True
            if not advanced:
                break
            level += 1

        return {
            "object_id": record.object_id,
            "object_path": str(record.object_path),
            "cluster_key": cluster_key,
            "active_clusters": active_clusters,
            "target_clusters": target_clusters,
            "candidate_genes": candidates,
        }

    def get_cluster_cell_ids(
        self,
        record: ObjectRecord,
        cluster_key: str,
        cluster_id: str,
    ) -> set[str]:
        adata = self.get_adata(record)
        if cluster_key not in adata.obs.columns:
            raise ValueError(f"Cluster key not found in obs: {cluster_key}")
        cluster_values = _obs_to_str_array(adata.obs, cluster_key, default="NA")
        mask = cluster_values.astype(str) == str(cluster_id)
        if not bool(mask.any()):
            raise ValueError(f"Cluster not found in {cluster_key}: {cluster_id}")
        cell_ids = self._get_cell_ids(record)[mask]
        return {str(cell_id) for cell_id in cell_ids.tolist()}

    def get_visible_highlight_values(
        self,
        record: ObjectRecord,
        highlight_cell_ids: set[str],
        indices: list[int],
    ) -> dict[str, Any]:
        cell_ids = self._get_cell_ids(record)
        index_array = np.asarray(indices, dtype=int)
        if index_array.size == 0:
            return {
                "object_id": record.object_id,
                "highlighted_total": int(len(highlight_cell_ids)),
                "highlighted_displayed": 0,
                "values": [],
            }
        if int(index_array.min()) < 0 or int(index_array.max()) >= cell_ids.shape[0]:
            raise ValueError("Requested point indices are out of bounds for the current object.")

        visible_mask = np.isin(cell_ids[index_array], list(highlight_cell_ids))
        return {
            "object_id": record.object_id,
            "highlighted_total": int(len(highlight_cell_ids)),
            "highlighted_displayed": int(visible_mask.sum()),
            "values": [
                {"index": int(index), "is_highlighted": bool(is_highlighted)}
                for index, is_highlighted in zip(index_array.tolist(), visible_mask.tolist(), strict=False)
            ],
        }

    def _prepare_concat_frames(self, source: ad.AnnData, dest: ad.AnnData) -> tuple[ad.AnnData, ad.AnnData]:
        obs_columns = list(dict.fromkeys(list(dest.obs.columns) + list(source.obs.columns)))
        for adata in (dest, source):
            for column in obs_columns:
                if column not in adata.obs.columns:
                    adata.obs[column] = pd.Series(pd.NA, index=adata.obs.index, dtype="string")
                adata.obs[column] = _coerce_series_for_union(adata.obs, column)
            adata.obs = adata.obs[obs_columns].copy()

        obsm_keys = sorted(set(dest.obsm.keys()) | set(source.obsm.keys()))
        for key in obsm_keys:
            if key in dest.obsm and key in source.obsm:
                continue
            reference = dest.obsm[key] if key in dest.obsm else source.obsm[key]
            width = int(np.asarray(reference).shape[1])
            if key not in dest.obsm:
                dest.obsm[key] = np.full((dest.n_obs, width), np.nan, dtype=float)
            if key not in source.obsm:
                source.obsm[key] = np.full((source.n_obs, width), np.nan, dtype=float)

        for adata in (dest, source):
            for key in list(adata.obsp.keys()):
                del adata.obsp[key]
        return source, dest

    def preview_move_cluster_between_objects(
        self,
        source_record: ObjectRecord,
        destination_record: ObjectRecord,
        cluster_key: str,
        cluster_id: str,
    ) -> dict[str, Any]:
        if source_record.object_id == destination_record.object_id:
            raise ValueError("Choose a different destination object.")

        source = self.get_adata(source_record)
        destination = self.get_adata(destination_record)

        if cluster_key not in source.obs.columns:
            raise ValueError(f"Cluster key not found in source object: {cluster_key}")
        if cluster_key not in destination.obs.columns:
            raise ValueError(
                f"Destination object does not contain cluster key: {cluster_key}. "
                "Select a destination that already has the same active cluster key."
            )
        if source.var_names.tolist() != destination.var_names.tolist():
            raise ValueError("Source and destination objects do not share identical var_names.")

        source_cluster_values = _obs_to_str_array(source.obs, cluster_key, default="NA")
        move_mask = source_cluster_values.astype(str) == str(cluster_id)
        n_moved = int(move_mask.sum())
        if n_moved == 0:
            raise ValueError(f"No cells found in source cluster: {cluster_id}")
        if n_moved == source.n_obs:
            raise ValueError("Refusing to move every cell out of the source object.")

        destination_cluster_values = _obs_to_str_array(destination.obs, cluster_key, default="NA")
        destination_cluster_ids = destination_cluster_values.astype(str).tolist()
        assigned_cluster_id = (
            _next_available_cluster_id(destination_cluster_ids, str(cluster_id))
            if str(cluster_id) in set(destination_cluster_ids)
            else str(cluster_id)
        )

        n_overwritten_cells = 0
        if "cell_id" in source.obs.columns and "cell_id" in destination.obs.columns:
            moving_cell_ids = set(_obs_to_str_array(source.obs, "cell_id")[move_mask].tolist())
            destination_cell_ids = set(_obs_to_str_array(destination.obs, "cell_id").tolist())
            n_overwritten_cells = int(len(moving_cell_ids & destination_cell_ids))

        display_column = _display_column_name(cluster_key)
        source_display_values = (
            _obs_to_str_array(source.obs, display_column, default="")
            if display_column in source.obs.columns
            else source_cluster_values.copy()
        )
        source_display_name = next(
            (
                _strip_origin_suffix(str(value).strip())
                for value in source_display_values[move_mask].tolist()
                if str(value).strip()
            ),
            str(cluster_id),
        )
        moved_display_name = f"{source_display_name} (from {source_record.lineage_name})"

        return {
            "source_object_id": source_record.object_id,
            "source_object_path": str(source_record.object_path),
            "destination_object_id": destination_record.object_id,
            "destination_object_path": str(destination_record.object_path),
            "cluster_key": cluster_key,
            "source_cluster_id": str(cluster_id),
            "assigned_cluster_id": assigned_cluster_id,
            "display_name": moved_display_name,
            "n_moved_cells": n_moved,
            "n_overwritten_cells": n_overwritten_cells,
        }

    def move_cluster_between_objects(
        self,
        source_record: ObjectRecord,
        destination_record: ObjectRecord,
        cluster_key: str,
        cluster_id: str,
        allow_overwrite: bool = False,
    ) -> dict[str, Any]:
        preview = self.preview_move_cluster_between_objects(
            source_record=source_record,
            destination_record=destination_record,
            cluster_key=cluster_key,
            cluster_id=cluster_id,
        )
        if preview["n_overwritten_cells"] > 0 and not allow_overwrite:
            raise ValueError(
                f"Destination object already contains {preview['n_overwritten_cells']} source cell_id values. "
                "Request a move preview and confirm overwrite before applying the move."
            )

        source = self.get_adata(source_record).copy()
        destination = self.get_adata(destination_record).copy()
        source_cluster_values = _obs_to_str_array(source.obs, cluster_key, default="NA")
        move_mask = source_cluster_values.astype(str) == str(cluster_id)
        n_moved = int(preview["n_moved_cells"])
        assigned_cluster_id = str(preview["assigned_cluster_id"])
        moved_display_name = str(preview["display_name"])
        display_column = _display_column_name(cluster_key)

        if display_column not in destination.obs.columns:
            destination.obs[display_column] = pd.Series(
                _obs_to_str_array(destination.obs, cluster_key, default=""),
                index=destination.obs_names,
                dtype=object,
            )

        moving = source[move_mask].copy()
        remaining = source[~move_mask].copy()
        if preview["n_overwritten_cells"] > 0 and "cell_id" in moving.obs.columns and "cell_id" in destination.obs.columns:
            moving_cell_ids = set(_obs_to_str_array(moving.obs, "cell_id").tolist())
            destination_keep_mask = ~np.isin(_obs_to_str_array(destination.obs, "cell_id"), list(moving_cell_ids))
            destination = destination[destination_keep_mask].copy()
        moving.obs_names = _unique_obs_names(moving.obs_names, destination.obs_names)
        moving.obs[cluster_key] = pd.Series(
            np.repeat(assigned_cluster_id, moving.n_obs),
            index=moving.obs_names,
            dtype=object,
        )
        moving.obs[display_column] = pd.Series(
            np.repeat(moved_display_name, moving.n_obs),
            index=moving.obs_names,
            dtype=object,
        )
        moving.obs["moved_from_object"] = pd.Series(
            np.repeat(source_record.lineage_name, moving.n_obs),
            index=moving.obs_names,
            dtype=object,
        )
        moving.obs["moved_from_path"] = pd.Series(
            np.repeat(str(source_record.object_path), moving.n_obs),
            index=moving.obs_names,
            dtype=object,
        )

        moving, destination = self._prepare_concat_frames(moving, destination)
        combined = ad.concat([destination, moving], join="outer", merge="same", index_unique=None)
        for adata in (combined, remaining):
            for key in list(adata.obsp.keys()):
                del adata.obsp[key]

        combined.uns = deepcopy(destination.uns)
        display_name_definitions = deepcopy(combined.uns.get("cluster_display_name_definitions", {}))
        destination_mapping = dict(display_name_definitions.get(cluster_key, {}))
        destination_mapping[assigned_cluster_id] = moved_display_name
        display_name_definitions[str(cluster_key)] = destination_mapping
        combined.uns["cluster_display_name_definitions"] = display_name_definitions
        if cluster_key == "reannot_label":
            combined.uns["reannotation_label_definitions"] = destination_mapping

        self._record_latest_move_snapshot(
            source_record=source_record,
            destination_record=destination_record,
            preview=preview,
        )
        remaining = self.recompute_embeddings(remaining, f"{source_record.lineage_name} after moving cluster {cluster_id}")
        combined = self.recompute_embeddings(
            combined,
            f"{destination_record.lineage_name} after receiving cluster {assigned_cluster_id}",
        )

        source_temp_path = self._stage_object_write(
            source_record,
            remaining,
            prefix=f"{source_record.object_path.stem}_move_out_",
        )
        try:
            destination_temp_path = self._stage_object_write(
                destination_record,
                combined,
                prefix=f"{destination_record.object_path.stem}_move_in_",
            )
        except Exception:
            source_temp_path.unlink(missing_ok=True)
            self._clear_latest_move_snapshot()
            raise

        try:
            self._commit_staged_object(source_record, remaining, source_temp_path)
            self._commit_staged_object(destination_record, combined, destination_temp_path)
        except Exception:
            source_temp_path.unlink(missing_ok=True)
            destination_temp_path.unlink(missing_ok=True)
            self._clear_latest_move_snapshot()
            raise

        return {
            "source_object_id": source_record.object_id,
            "source_object_path": str(source_record.object_path),
            "destination_object_id": destination_record.object_id,
            "destination_object_path": str(destination_record.object_path),
            "cluster_key": cluster_key,
            "cluster_id": assigned_cluster_id,
            "display_name": moved_display_name,
            "n_moved_cells": n_moved,
            "n_overwritten_cells": int(preview["n_overwritten_cells"]),
        }

    def polygon_select(
        self,
        record: ObjectRecord,
        embedding_key: str,
        polygons: list[dict[str, Any]],
        cluster_key: str | None,
    ) -> dict[str, Any]:
        adata = self.get_adata(record)
        coords = np.asarray(adata.obsm[embedding_key])[:, :2]
        cluster_values = (
            _obs_to_str_array(adata.obs, cluster_key, default="all")
            if cluster_key
            else np.full(adata.n_obs, "all", dtype=object)
        )
        selected_mask = np.zeros(adata.n_obs, dtype=bool)
        polygon_summaries: list[dict[str, Any]] = []
        for polygon in polygons:
            polygon_mask = points_in_polygon(coords, np.asarray(polygon["vertices"], dtype=float))
            selected_mask |= polygon_mask
            cluster_counts = pd.Series(cluster_values[polygon_mask]).value_counts().sort_index()
            polygon_summaries.append(
                {
                    "polygon_id": polygon["polygon_id"],
                    "n_cells": int(polygon_mask.sum()),
                    "clusters": [
                        {"cluster": str(cluster), "n_cells": int(count)}
                        for cluster, count in cluster_counts.items()
                    ],
                }
            )

        selected_indices = np.flatnonzero(selected_mask)
        selected_cell_ids = (
            _obs_to_str_array(adata.obs, "cell_id")[selected_indices]
            if "cell_id" in adata.obs.columns
            else adata.obs_names.to_numpy(dtype=object)[selected_indices]
        )
        return {
            "total_selected_cells": int(selected_indices.size),
            "selected_indices": selected_indices.tolist(),
            "selected_cell_ids": [str(cell_id) for cell_id in selected_cell_ids.tolist()],
            "polygon_summaries": polygon_summaries,
        }

    def get_features(self, record: ObjectRecord, pca_key: str = "X_pca_lineage") -> np.ndarray:
        adata = self.get_adata(record)
        key = pca_key if pca_key in adata.obsm else next((k for k in adata.obsm if "pca" in k.lower()), None)
        if key is None:
            raise KeyError("No PCA embedding available in obsm.")
        return np.asarray(adata.obsm[key], dtype=float)

    def get_graph(self, record: ObjectRecord) -> sparse.spmatrix | None:
        adata = self.get_adata(record)
        graph = adata.obsp.get("lineage_connectivities")
        if graph is None:
            return None
        return graph.tocsr() if sparse.issparse(graph) else sparse.csr_matrix(graph)

    def get_cluster_label_editor(self, record: ObjectRecord, cluster_key: str) -> dict[str, Any]:
        adata = self.get_adata(record)
        if cluster_key not in adata.obs.columns:
            raise ValueError(f"Cluster key not found in obs: {cluster_key}")

        cluster_values = _obs_to_str_array(adata.obs, cluster_key, default="NA")
        display_column = _display_column_name(cluster_key)
        existing_display = (
            _obs_to_str_array(adata.obs, display_column, default="")
            if display_column in adata.obs.columns
            else np.full(adata.n_obs, "", dtype=object)
        )

        rows: list[dict[str, Any]] = []
        counts = pd.Series(cluster_values).value_counts(sort=False)
        ordered_cluster_ids = pd.Index(cluster_values).drop_duplicates().tolist()
        for cluster_id in ordered_cluster_ids:
            mask = cluster_values == cluster_id
            display_values = pd.Series(existing_display[mask]).replace("", pd.NA).dropna()
            display_name = str(display_values.iloc[0]) if not display_values.empty else None
            rows.append(
                {
                    "cluster_id": str(cluster_id),
                    "n_cells": int(counts.loc[cluster_id]),
                    "display_name": display_name,
                }
            )

        return {
            "object_id": record.object_id,
            "object_path": str(record.object_path),
            "cluster_key": cluster_key,
            "display_column": display_column,
            "rows": rows,
        }

    def save_cluster_label_editor(
        self,
        record: ObjectRecord,
        cluster_key: str,
        mapping: dict[str, str],
        display_column: str | None = None,
    ) -> dict[str, Any]:
        adata = self.get_adata(record).copy()
        if cluster_key not in adata.obs.columns:
            raise ValueError(f"Cluster key not found in obs: {cluster_key}")

        display_column = display_column or _display_column_name(cluster_key)
        cluster_values = _obs_to_str_array(adata.obs, cluster_key, default="NA")
        normalized_mapping = {str(key): value.strip() for key, value in mapping.items() if value.strip()}
        display_values = np.asarray(
            [normalized_mapping.get(str(cluster_id), str(cluster_id)) for cluster_id in cluster_values],
            dtype=object,
        )
        adata.obs[display_column] = pd.Series(display_values, index=adata.obs_names, dtype=object)

        display_name_definitions = deepcopy(adata.uns.get("cluster_display_name_definitions", {}))
        display_name_definitions[str(cluster_key)] = normalized_mapping
        adata.uns["cluster_display_name_definitions"] = display_name_definitions

        if cluster_key == "reannot_label":
            adata.uns["reannotation_label_definitions"] = normalized_mapping

        self._write_object(record, adata, prefix=f"{record.object_path.stem}_display_labels_")
        return {
            "object_id": record.object_id,
            "object_path": str(record.object_path),
            "cluster_key": cluster_key,
            "display_column": display_column,
            "n_updated": int(len(normalized_mapping)),
        }

    def promote_reannot_new_to_canonical(self, record: ObjectRecord) -> dict[str, Any]:
        adata = self.get_adata(record).copy()
        source_label_key = "reannot_label_new"
        source_display_key = "reannot_display_label_new"
        target_label_key = "reannot_label"
        target_display_key = "reannot_display_label"

        if source_label_key not in adata.obs.columns:
            raise ValueError(f"Source label key not found in obs: {source_label_key}")
        if source_display_key not in adata.obs.columns:
            raise ValueError(f"Source display key not found in obs: {source_display_key}")

        adata.obs[target_label_key] = pd.Series(
            _obs_to_str_array(adata.obs, source_label_key, default=""),
            index=adata.obs_names,
            dtype=object,
        )
        adata.obs[target_display_key] = pd.Series(
            _obs_to_str_array(adata.obs, source_display_key, default=""),
            index=adata.obs_names,
            dtype=object,
        )

        display_name_definitions = deepcopy(adata.uns.get("cluster_display_name_definitions", {}))
        source_display_map = self._display_mapping(adata, source_label_key)
        display_name_definitions[target_label_key] = {
            str(key): str(value) for key, value in source_display_map.items()
        }
        adata.uns["cluster_display_name_definitions"] = display_name_definitions
        adata.uns["reannotation_label_definitions"] = {
            str(key): str(value) for key, value in source_display_map.items()
        }

        self._write_object(record, adata, prefix=f"{record.object_path.stem}_promote_new_")
        return {
            "object_id": record.object_id,
            "object_path": str(record.object_path),
            "source_label_key": source_label_key,
            "source_display_key": source_display_key,
            "target_label_key": target_label_key,
            "target_display_key": target_display_key,
        }

    def _write_object(self, record: ObjectRecord, adata: ad.AnnData, prefix: str) -> None:
        temp_path = self._stage_object_write(record, adata, prefix=prefix)
        try:
            self._commit_staged_object(record, adata, temp_path)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

    def _stage_object_write(self, record: ObjectRecord, adata: ad.AnnData, prefix: str) -> Path:
        adata.obs = _normalize_obs_for_write(adata.obs)
        with NamedTemporaryFile(
            prefix=prefix,
            suffix=".h5ad",
            dir=record.object_path.parent,
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)

        try:
            ad.settings.allow_write_nullable_strings = True
            adata.write_h5ad(temp_path, convert_strings_to_categoricals=False)
            with h5py.File(temp_path, "r") as saved:
                missing = sorted({"X", "obs", "var", "obsm", "uns"}.difference(saved.keys()))
                if missing:
                    raise ValueError(f"Missing required groups after save: {', '.join(missing)}")
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

        return temp_path

    def _commit_staged_object(self, record: ObjectRecord, adata: ad.AnnData, temp_path: Path) -> None:
        temp_path.replace(record.object_path)
        self.replace_cached(record.object_id, adata)


adata_service = AnnDataService()
