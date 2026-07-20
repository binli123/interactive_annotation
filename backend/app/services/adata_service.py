from __future__ import annotations

import base64
import io
import json
import os
import re
import shutil
import threading
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
from app.models.state import ObjectRecord, SessionState
from app.services.polygon_ops import points_in_polygon
from app.services.propagation import build_knn_graph
from app.services.registry import registry
from app.services.sampling import priority_stratified_sample_indices, stratified_sample_indices

try:
    from anndata.io import read_elem, write_elem
except ImportError:  # anndata < 0.10.6
    from anndata.experimental import read_elem, write_elem


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


def _h5_write_obs_column(f: h5py.File, column: str, values: np.ndarray) -> None:
    """Write one obs column in place, appending it to obs's column-order if new."""
    if column in f["obs"]:
        del f["obs"][column]
    if values.dtype.kind in ("f", "i", "u", "b"):
        write_elem(f["obs"], column, values)
    else:
        write_elem(f["obs"], column, pd.array(np.asarray(values, dtype=object), dtype="string"))
    column_order = [str(c) for c in f["obs"].attrs.get("column-order", [])]
    if column not in column_order:
        f["obs"].attrs["column-order"] = np.array(column_order + [column], dtype=object)


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


# ─────────────────────────────────────────────────────────────────────
# h5py helpers: selective, memory-efficient reads from .h5ad files.
# These read only what's requested — never the X matrix or full obsm.
# ─────────────────────────────────────────────────────────────────────

_H5_CLUSTER_EXCLUDED = {
    "_index", "cell_id", "sample_id", "region", "run_id", "original_id",
    "cell_index", "segmentation_method", "z_level", "barcode",
    "x_centroid", "y_centroid",
}
_H5_CLUSTER_PREFERRED = [
    "reannot_display_label", "reannot_label", "final_substate_refined",
    "round2_substate", "round1_auto_substate", "celltypist_prediction",
    "final_valid_lineage", "lineage",
]
_H5_QC_COLUMNS = {
    "n_genes_by_counts", "total_counts", "pct_counts_mt",
    "n_counts", "log1p_total_counts", "nCount_Xenium", "nFeature_Xenium",
}


def _h5_obs_col_names(h5: h5py.File) -> list[str]:
    obs_grp = h5["obs"]
    col_order = obs_grp.attrs.get("column-order", None)
    if col_order is not None:
        return [str(c) for c in col_order]
    return [k for k in obs_grp.keys() if k != "__categories"]


def _h5_n_obs(h5: h5py.File) -> int:
    obs_grp = h5["obs"]
    idx_col = str(obs_grp.attrs.get("_index", ""))
    if idx_col and idx_col in obs_grp:
        return int(obs_grp[idx_col].shape[0])
    for k in obs_grp.keys():
        item = obs_grp[k]
        if isinstance(item, h5py.Dataset):
            return int(item.shape[0])
        if isinstance(item, h5py.Group) and "codes" in item:
            return int(item["codes"].shape[0])
    return 0


def _h5_obs_names(h5: h5py.File) -> np.ndarray:
    obs_grp = h5["obs"]
    idx_col = str(obs_grp.attrs.get("_index", ""))
    if not idx_col or idx_col not in obs_grp:
        for k in obs_grp.keys():
            if isinstance(obs_grp[k], h5py.Dataset):
                idx_col = k
                break
    raw = obs_grp[idx_col][:]
    return np.array([v.decode() if isinstance(v, bytes) else v for v in raw], dtype=object)


def _h5_obs_col(h5: h5py.File, col: str, default: str | None = None) -> np.ndarray:
    obs_grp = h5["obs"]
    if col not in obs_grp:
        if default is not None:
            return np.full(_h5_n_obs(h5), default, dtype=object)
        raise KeyError(f"Column '{col}' not found in obs")
    item = obs_grp[col]
    if isinstance(item, h5py.Group):
        if "codes" not in item:
            if "values" in item:
                # Nullable array (e.g. nullable-string-array): {values, mask} with
                # mask[i] True meaning the entry is missing/null.
                raw = item["values"][:]
                values_arr = np.array(
                    [v.decode() if isinstance(v, bytes) else v for v in raw], dtype=object
                )
                if "mask" in item:
                    missing = np.asarray(item["mask"][:], dtype=bool)
                    values_arr[missing] = default if default is not None else ""
                return values_arr
            # Non-categorical group — fall back to default.
            if default is not None:
                return np.full(_h5_n_obs(h5), default, dtype=object)
            raise KeyError(f"Column '{col}' has an unsupported structure")
        codes = item["codes"][:]
        cats_node = item.get("categories")
        if isinstance(cats_node, h5py.Dataset):
            cats_raw = cats_node[:]
        elif isinstance(cats_node, h5py.Group) and "values" in cats_node:
            # Newer AnnData nullable-string format: categories stored as {mask, values}.
            cats_raw = cats_node["values"][:]
        else:
            if default is not None:
                return np.full(_h5_n_obs(h5), default, dtype=object)
            raise KeyError(f"Column '{col}' has an unsupported categorical structure")
        cats = np.array([c.decode() if isinstance(c, bytes) else c for c in cats_raw], dtype=object)
        valid = codes >= 0
        result = np.empty(len(codes), dtype=object)
        result[valid] = cats[codes[valid].astype(int)]
        result[~valid] = ""
        return result
    data = item[:]
    if data.dtype.kind == "S":
        return np.array([v.decode() for v in data], dtype=object)
    if data.dtype.kind == "O":
        return np.array([v.decode() if isinstance(v, bytes) else v for v in data], dtype=object)
    return data


def _h5_obs_col_is_numeric(h5: h5py.File, col: str) -> bool:
    obs_grp = h5["obs"]
    if col not in obs_grp:
        return False
    item = obs_grp[col]
    if isinstance(item, h5py.Group):
        return False
    return item.dtype.kind in ("f", "i", "u", "b")


def _h5_obsm(h5: h5py.File, key: str) -> np.ndarray:
    return np.asarray(h5["obsm"][key][:], dtype=np.float32)


def _h5_var_names(h5: h5py.File) -> np.ndarray:
    var_grp = h5["var"]
    idx_col = str(var_grp.attrs.get("_index", ""))
    if not idx_col or idx_col not in var_grp:
        for k in var_grp.keys():
            if isinstance(var_grp[k], h5py.Dataset):
                idx_col = k
                break
    raw = var_grp[idx_col][:]
    return np.array([v.decode() if isinstance(v, bytes) else str(v) for v in raw], dtype=object)


def _h5_obsp_sparse(h5: h5py.File, key: str) -> sparse.spmatrix:
    g = h5["obsp"][key]
    data = g["data"][:]
    indices_arr = g["indices"][:]
    indptr = g["indptr"][:]
    shape_attr = g.attrs.get("shape", None)
    if shape_attr is not None:
        shape = tuple(int(s) for s in shape_attr)
    else:
        n = len(indptr) - 1
        shape = (n, n)
    return sparse.csr_matrix((data, indices_arr, indptr), shape=shape)


def _h5_gene_expression_for_indices(
    h5: h5py.File, gene_name: str, sampled_indices: np.ndarray
) -> np.ndarray | None:
    """Read one gene's expression for a specific subset of cells only.
    Uses per-row reads for CSR — total data read is tiny (sampled_cells × avg_nnz_per_cell).
    Returns None if X is absent; raises ValueError if gene is not found."""
    if "var" not in h5 or "X" not in h5:
        return None
    var_names = _h5_var_names(h5)
    matches = np.where(var_names == gene_name)[0]
    if len(matches) == 0:
        raise ValueError(f"Gene not found in object: {gene_name}")
    gene_idx = int(matches[0])
    n_sampled = len(sampled_indices)
    result = np.zeros(n_sampled, dtype=float)
    x_node = h5["X"]

    if isinstance(x_node, h5py.Dataset):
        # Dense: fancy-index the rows we need
        return np.asarray(x_node[sampled_indices.tolist(), gene_idx], dtype=float)

    if isinstance(x_node, h5py.Group):
        if "indptr" not in x_node or "indices" not in x_node or "data" not in x_node:
            return None
        encoding = str(
            x_node.attrs.get("encoding-type", "") or x_node.attrs.get("h5sparse_format", "")
        ).lower()

        if "csc" in encoding:
            # CSC: one slice covers the entire gene column
            indptr = x_node["indptr"][:]
            col_data = x_node["data"][indptr[gene_idx] : indptr[gene_idx + 1]]
            col_rows = x_node["indices"][indptr[gene_idx] : indptr[gene_idx + 1]]
            row_to_val = dict(zip(col_rows.tolist(), col_data.tolist()))
            for i, cell_idx in enumerate(sampled_indices.tolist()):
                result[i] = float(row_to_val.get(int(cell_idx), 0.0))
            return result

        # CSR: load indptr (22 MB for 2.8M cells), then read each sampled row's slice.
        # Total data read = n_sampled × avg_nnz_per_cell ≈ 10k × 150 entries = 12 MB.
        indptr = x_node["indptr"][:]
        sort_order = np.argsort(sampled_indices)
        sorted_cell_indices = sampled_indices[sort_order]
        for rank, cell_idx in enumerate(sorted_cell_indices.tolist()):
            start = int(indptr[cell_idx])
            end = int(indptr[cell_idx + 1])
            if end > start:
                cell_cols = x_node["indices"][start:end]
                hit = np.where(cell_cols == gene_idx)[0]
                if len(hit):
                    result[sort_order[rank]] = float(x_node["data"][int(start + hit[0])])
        return result

    return None


def _h5_build_view_submatrix(
    h5: h5py.File, sampled_indices: np.ndarray
) -> tuple[sparse.csc_matrix, np.ndarray] | None:
    """Build a CSC submatrix for the sampled cells using just 2 h5py fancy-index reads.

    Old approach: 50k × 2 individual h5py slice reads = ~100k h5py calls.
    New approach: build flat_positions (vectorized numpy), then read indices and data
    arrays in ONE h5py call each. Convert the resulting CSR submatrix to CSC so that
    any gene column extraction is an instant O(nnz_in_gene) numpy operation.

    Memory: ~120MB peak during build; ~60MB stored per view (50k cells × ~150 entries).
    """
    if "X" not in h5 or "var" not in h5:
        return None
    x_node = h5["X"]
    var_names = _h5_var_names(h5)
    n_genes = len(var_names)
    n_sampled = len(sampled_indices)

    if isinstance(x_node, h5py.Dataset):
        # Dense X: read the sub-rows directly.
        sub = np.asarray(x_node[sorted(sampled_indices.tolist()), :], dtype=np.float32)
        # re-order rows to match original sampled_indices order
        inv = np.argsort(np.argsort(sampled_indices))
        return sparse.csc_matrix(sub[inv]), var_names

    if not isinstance(x_node, h5py.Group):
        return None
    if "indptr" not in x_node or "indices" not in x_node or "data" not in x_node:
        return None

    encoding = str(
        x_node.attrs.get("encoding-type", "") or x_node.attrs.get("h5sparse_format", "")
    ).lower()

    if "csc" in encoding:
        # CSC: per-gene column reads are already cheap; submatrix not needed.
        return None

    # CSR path: sort cells for sequential h5py access
    sort_order = np.argsort(sampled_indices)
    sorted_cell_indices = sampled_indices[sort_order]

    indptr = x_node["indptr"][:]
    starts = indptr[sorted_cell_indices].astype(np.int64)
    ends = indptr[sorted_cell_indices + 1].astype(np.int64)
    row_lengths = ends - starts
    total_nnz = int(row_lengths.sum())

    if total_nnz == 0:
        return sparse.csc_matrix((n_sampled, n_genes), dtype=np.float32), var_names

    # Build flat file-positions for all needed entries (vectorized, no Python loops).
    cumlen = np.zeros(n_sampled + 1, dtype=np.int64)
    np.cumsum(row_lengths, out=cumlen[1:])
    inner = np.arange(total_nnz, dtype=np.int64)
    inner -= np.repeat(cumlen[:-1], row_lengths)
    flat_positions = np.repeat(starts, row_lengths) + inner  # sorted ↑ → efficient HDF5 read

    # TWO h5py fancy-index reads instead of n_sampled×2 slice reads.
    all_col_indices = x_node["indices"][flat_positions]
    all_data = x_node["data"][flat_positions].astype(np.float32)

    # Row indices in original (unsorted) order
    sorted_row_ids = np.repeat(np.arange(n_sampled, dtype=np.int32), row_lengths)
    orig_row_ids = sort_order[sorted_row_ids]

    csr = sparse.csr_matrix(
        (all_data, (orig_row_ids, all_col_indices.astype(np.int32))),
        shape=(n_sampled, n_genes),
    )
    return csr.tocsc(), var_names


def _h5_category_count(item: h5py.Group) -> int:
    """Count categories for a categorical obs Group, tolerating both plain-Dataset
    and newer nullable-string-array ({mask, values}) category encodings."""
    cats_node = item.get("categories")
    if isinstance(cats_node, h5py.Dataset):
        return int(cats_node.shape[0])
    if isinstance(cats_node, h5py.Group) and "values" in cats_node:
        return int(cats_node["values"].shape[0])
    return 0


def _h5_cluster_key_candidates(h5: h5py.File, obs_cols: list[str]) -> list[str]:
    obs_grp = h5["obs"]
    candidates: set[str] = set()
    for col in obs_cols:
        if col in _H5_CLUSTER_EXCLUDED:
            continue
        if col not in obs_grp:
            continue
        item = obs_grp[col]
        if col.startswith("leiden_") or col in _H5_CLUSTER_PREFERRED:
            candidates.add(col)
            continue
        if isinstance(item, h5py.Group) and "categories" in item:
            n_cats = _h5_category_count(item)
            if 2 <= n_cats <= 256:
                candidates.add(col)
        # non-categorical strings: skip to avoid expensive unique-count load
    ordered: list[str] = []
    seen: set[str] = set()
    for col in _H5_CLUSTER_PREFERRED:
        if col in candidates and col not in seen:
            ordered.append(col)
            seen.add(col)
    for col in sorted(candidates):
        if col not in seen:
            ordered.append(col)
            seen.add(col)
    return ordered


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
            or isinstance(series.dtype, pd.CategoricalDtype)
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
        # Gene expression cache: keyed by "{object_id}:{indices_hash}" → {gene_name: values_array}
        # Evicted automatically when the displayed point set changes (new sampling or object switch).
        self._gene_expr_cache: dict[str, np.ndarray] = {}
        self._gene_expr_cache_slot: str | None = None  # current slot key
        # View-token store: maps token → sampled indices array so gene requests don't re-send indices.
        self._view_indices: dict[str, np.ndarray] = {}
        # Submatrix cache: full CSC sparse matrix for the currently displayed cells.
        # Built on first gene query; makes all subsequent gene queries instant (column extraction only).
        # Only one view is cached at a time — evicted when the displayed point set changes.
        self._view_submatrix_token: str | None = None
        self._view_submatrix_data: tuple | None = None  # (csc_matrix, var_names)
        self._view_submatrix_lock = threading.Lock()
        # KNN propagation graph cache: keyed by "{object_id}:{n_neighbors}:{pca_key}".
        # Building this graph is the expensive part of whole_lineage propagation — cache
        # it so repeated propagate() calls (tuning thresholds, re-running) are instant.
        self._graph_cache: dict[str, sparse.spmatrix] = {}

    def _touch(self, object_id: str, adata: ad.AnnData) -> ad.AnnData:
        self._cache[object_id] = adata
        self._cache.move_to_end(object_id)
        while len(self._cache) > self.max_cached_objects:
            evicted_object_id, evicted = self._cache.popitem(last=False)
            self._cell_id_cache.pop(evicted_object_id, None)
            if getattr(evicted, "isbacked", False):
                evicted.file.close()
        return adata

    def _evict_graph_cache(self, object_id: str) -> None:
        for key in [k for k in self._graph_cache if k.startswith(f"{object_id}:")]:
            self._graph_cache.pop(key, None)

    def replace_cached(self, object_id: str, adata: ad.AnnData) -> ad.AnnData:
        cached = self._cache.pop(object_id, None)
        if cached is not None and getattr(cached, "isbacked", False):
            cached.file.close()
        self._cell_id_cache.pop(object_id, None)
        self._evict_graph_cache(object_id)
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
        self._evict_graph_cache(object_id)

    def _get_cell_ids(self, record: ObjectRecord) -> np.ndarray:
        cached = self._cell_id_cache.get(record.object_id)
        if cached is not None:
            return cached
        with h5py.File(record.object_path, "r") as f:
            obs_cols = _h5_obs_col_names(f)
            cell_ids = _h5_obs_col(f, "cell_id") if "cell_id" in obs_cols else _h5_obs_names(f)
        normalized = np.asarray(cell_ids, dtype=object).astype(str, copy=False)
        self._cell_id_cache[record.object_id] = normalized
        return normalized

    def _move_undo_dir(self) -> Path:
        path = settings.project_root / ".move_undo"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _object_change_undo_dir(self) -> Path:
        path = settings.project_root / ".object_change_undo"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _object_change_undo_metadata_path(self) -> Path:
        return self._object_change_undo_dir() / "latest_change.json"

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

    def _clear_latest_object_change_snapshot(self) -> None:
        metadata_path = self._object_change_undo_metadata_path()
        snapshot_paths: list[Path] = []
        if metadata_path.exists():
            try:
                payload = json.loads(metadata_path.read_text())
                snapshot_paths = [
                    Path(str(item.get("snapshot_path", "")))
                    for item in payload.get("objects", [])
                    if str(item.get("snapshot_path", "")).strip()
                ]
            except Exception:
                snapshot_paths = []

        for path in snapshot_paths:
            path.unlink(missing_ok=True)
        metadata_path.unlink(missing_ok=True)

        undo_dir = self._object_change_undo_dir()
        for path in undo_dir.glob("latest_object_*.h5ad"):
            path.unlink(missing_ok=True)

    def _latest_object_change_status_payload(self) -> dict[str, Any]:
        metadata_path = self._object_change_undo_metadata_path()
        if not metadata_path.exists():
            return {"available": False}

        try:
            payload = json.loads(metadata_path.read_text())
        except Exception:
            self._clear_latest_object_change_snapshot()
            return {"available": False}

        objects = payload.get("objects", [])
        if not isinstance(objects, list) or not objects:
            self._clear_latest_object_change_snapshot()
            return {"available": False}

        for item in objects:
            snapshot_path = Path(str(item.get("snapshot_path", "")))
            if not snapshot_path.exists():
                self._clear_latest_object_change_snapshot()
                return {"available": False}

        object_ids = [str(item.get("object_id", "")) for item in objects]
        object_paths = [str(item.get("object_path", "")) for item in objects]
        return {
            "available": True,
            "change_type": str(payload.get("change_type") or ""),
            "description": str(payload.get("description") or ""),
            "object_ids": object_ids,
            "object_paths": object_paths,
            "object_count": len(objects),
            "created_at": str(payload.get("created_at") or ""),
        }

    def get_latest_object_change_status(self) -> dict[str, Any]:
        return self._latest_object_change_status_payload()

    def _record_latest_object_change_snapshot(
        self,
        *,
        records: list[ObjectRecord],
        change_type: str,
        description: str,
    ) -> None:
        self._clear_latest_object_change_snapshot()
        if change_type != "move_cluster":
            self._clear_latest_move_snapshot()

        payload_objects: list[dict[str, Any]] = []
        copied_paths: list[Path] = []
        undo_dir = self._object_change_undo_dir()
        try:
            for index, record in enumerate(records):
                snapshot_path = undo_dir / f"latest_object_{index}_{record.object_id}.h5ad"
                shutil.copy2(record.object_path, snapshot_path)
                copied_paths.append(snapshot_path)
                payload_objects.append(
                    {
                        "object_id": record.object_id,
                        "object_path": str(record.object_path),
                        "lineage_name": record.lineage_name,
                        "snapshot_path": str(snapshot_path),
                    }
                )
        except Exception:
            for path in copied_paths:
                path.unlink(missing_ok=True)
            raise

        payload = {
            "change_type": str(change_type),
            "description": str(description),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "objects": payload_objects,
        }
        self._object_change_undo_metadata_path().write_text(json.dumps(payload, indent=2))

    def undo_latest_object_change(self) -> dict[str, Any]:
        status = self._latest_object_change_status_payload()
        if not status.get("available"):
            raise ValueError("No object-change snapshot is available to undo.")

        metadata_path = self._object_change_undo_metadata_path()
        payload = json.loads(metadata_path.read_text())
        objects = payload.get("objects", [])
        if not objects:
            self._clear_latest_object_change_snapshot()
            raise ValueError("The saved object-change snapshot is incomplete and cannot be restored.")

        restored_records: list[ObjectRecord] = []
        for item in objects:
            object_path = Path(str(item["object_path"]))
            lineage_name = str(item.get("lineage_name") or object_path.stem)
            record = registry.build_record(
                object_path=object_path,
                lineage_name=lineage_name,
                lineage_dir=object_path.parent,
            )
            snapshot_path = Path(str(item["snapshot_path"]))
            if not snapshot_path.exists():
                self._clear_latest_object_change_snapshot()
                raise ValueError("The saved object-change snapshot is incomplete and cannot be restored.")
            restore_path = object_path.with_suffix(object_path.suffix + ".undo_restore")
            shutil.copy2(snapshot_path, restore_path)
            restore_path.replace(object_path)
            self.invalidate_cached(record.object_id)
            restored_records.append(record)

        if str(payload.get("change_type")) == "move_cluster":
            self._clear_latest_move_snapshot()
        self._clear_latest_object_change_snapshot()

        return {
            "available": False,
            "restored": True,
            "change_type": str(payload.get("change_type") or ""),
            "description": str(payload.get("description") or ""),
            "object_ids": [record.object_id for record in restored_records],
            "object_paths": [str(record.object_path) for record in restored_records],
            "object_count": len(restored_records),
            "created_at": str(payload.get("created_at") or ""),
        }

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
        with h5py.File(record.object_path, "r") as f:
            embedding_keys = sorted(f["obsm"].keys()) if "obsm" in f else []
            obsp_keys = list(f["obsp"].keys()) if "obsp" in f else []
            obs_cols = _h5_obs_col_names(f)
            n_obs = _h5_n_obs(f)
            n_vars = len(_h5_var_names(f)) if "var" in f else 0
            cluster_keys = _h5_cluster_key_candidates(f, obs_cols)
            has_spatial = "spatial" in (f["obsm"] if "obsm" in f else {})

        if not embedding_keys:
            raise ValueError(
                f"Object has no embeddings available for viewing: {record.object_path}. "
                "Use a lineage object with saved UMAP coordinates."
            )
        pca_keys = [k for k in embedding_keys if "pca" in k.lower()]
        default_embedding = (
            "X_umap" if "X_umap" in embedding_keys
            else "X_umap_lineage" if "X_umap_lineage" in embedding_keys
            else embedding_keys[0]
        )
        default_cluster = next(
            (k for k in ("reannot_label", "reannot_display_label") if k in cluster_keys), None
        )
        if default_cluster is None and record.lineage_name == "Global" and "final_valid_lineage" in cluster_keys:
            default_cluster = "final_valid_lineage"
        if default_cluster is None:
            default_cluster = cluster_keys[0] if cluster_keys else None
        sample_cols = [c for c in ("sample_id", "region", "lineage", "final_valid_lineage") if c in obs_cols]
        return {
            "object_id": record.object_id,
            "lineage_name": record.lineage_name,
            "object_path": str(record.object_path),
            "shape": (int(n_obs), int(n_vars)),
            "cluster_keys": cluster_keys,
            "embedding_keys": embedding_keys,
            "pca_keys": pca_keys,
            "default_embedding_key": default_embedding,
            "default_cluster_key": default_cluster,
            "has_connectivities": "lineage_connectivities" in obsp_keys,
            "has_distances": "lineage_distances" in obsp_keys,
            "has_spatial": has_spatial,
            "summary_resolution_trials": record.resolution_trials,
            "obs_columns": obs_cols,
            "sample_columns": sample_cols,
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

        spatial_coords: np.ndarray | None = None
        if "spatial" in adata.obsm:
            spatial_coords = np.asarray(adata.obsm["spatial"])[:, :2]

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
                "sx": float(spatial_coords[obs_index, 0]) if spatial_coords is not None else None,
                "sy": float(spatial_coords[obs_index, 1]) if spatial_coords is not None else None,
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
        _LABEL_COLS = ("reannot_display_label", "reannot_label", "current_label", "celltypist_label")
        _SCORE_COLS = ("reannot_confidence", "current_score", "celltypist_confidence")
        with h5py.File(record.object_path, "r") as f:
            coords = _h5_obsm(f, embedding_key)[:, :2]
            n_obs = coords.shape[0]
            obs_grp_keys = set(f["obs"].keys())
            clusters = (
                _h5_obs_col(f, cluster_key, default="all")
                if cluster_key and cluster_key in obs_grp_keys
                else np.full(n_obs, "all", dtype=object)
            )
            label_col = next((c for c in _LABEL_COLS if c in obs_grp_keys), None)
            current_labels = _h5_obs_col(f, label_col, default="") if label_col else None
            score_col = next((c for c in _SCORE_COLS if c in obs_grp_keys), None)
            current_scores = np.asarray(_h5_obs_col(f, score_col), dtype=float) if score_col else None
            sample_id_arr = _h5_obs_col(f, "sample_id", default="") if "sample_id" in obs_grp_keys else None
            region_arr = _h5_obs_col(f, "region", default="") if "region" in obs_grp_keys else None
            lineage_arr = _h5_obs_col(f, "lineage", default="") if "lineage" in obs_grp_keys else None
            has_spatial = "obsm" in f and "spatial" in f["obsm"]
            spatial_coords = _h5_obsm(f, "spatial")[:, :2] if has_spatial else None
            obs_names_arr = _h5_obs_names(f)

            # Sample first so gene expression reads only the displayed rows
            indices = stratified_sample_indices(
                labels=clusters.astype(str),
                max_points=max_points,
                min_per_cluster=min_per_cluster,
                max_per_cluster=max_per_cluster if max_per_cluster > 0 else None,
                random_seed=random_seed,
            )

            gene_expr: np.ndarray | None = None
            gene_expr_warning: str | None = None
            if gene_name:
                try:
                    gene_expr = _h5_gene_expression_for_indices(f, gene_name, indices)
                except Exception as exc:
                    gene_expr_warning = str(exc)
        cell_ids = self._get_cell_ids(record)
        points = []
        for local_pos, obs_idx in enumerate(indices.tolist()):
            score_val = float(current_scores[obs_idx]) if current_scores is not None else np.nan
            # gene_expr is indexed by local_pos (one entry per sampled cell, not per all cells)
            gene_val = float(gene_expr[local_pos]) if gene_expr is not None else np.nan
            label_val = str(current_labels[obs_idx]) if current_labels is not None else ""
            points.append({
                "index": int(obs_idx),
                "obs_name": str(obs_names_arr[obs_idx]),
                "cell_id": str(cell_ids[obs_idx]),
                "x": float(coords[obs_idx, 0]),
                "y": float(coords[obs_idx, 1]),
                "cluster": str(clusters[obs_idx]),
                "sample_id": str(sample_id_arr[obs_idx]) if sample_id_arr is not None else None,
                "region": str(region_arr[obs_idx]) if region_arr is not None else None,
                "lineage": str(lineage_arr[obs_idx]) if lineage_arr is not None else None,
                "current_label": label_val if label_val else None,
                "current_score": None if np.isnan(score_val) else score_val,
                "gene_expression": None if np.isnan(gene_val) else gene_val,
                "sx": float(spatial_coords[obs_idx, 0]) if spatial_coords is not None else None,
                "sy": float(spatial_coords[obs_idx, 1]) if spatial_coords is not None else None,
            })
        view_token = f"{record.object_id}:{hash(indices.tobytes())}"
        self._view_indices[view_token] = indices
        result: dict[str, Any] = {
            "object_id": record.object_id,
            "points": points,
            "embedding_key": embedding_key,
            "cluster_key": cluster_key,
            "gene_name": gene_name,
            "total_cells": int(n_obs),
            "displayed_cells": int(indices.size),
            "view_token": view_token,
        }
        if gene_expr_warning:
            result["gene_expression_warning"] = gene_expr_warning
        return result

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
        _LABEL_COLS = ("reannot_display_label", "reannot_label", "current_label", "celltypist_label")
        _SCORE_COLS = ("reannot_confidence", "current_score", "celltypist_confidence")
        with h5py.File(record.object_path, "r") as f:
            coords = _h5_obsm(f, embedding_key)[:, :2]
            n_obs = coords.shape[0]
            obs_grp_keys = set(f["obs"].keys())
            clusters = (
                _h5_obs_col(f, cluster_key, default="all")
                if cluster_key and cluster_key in obs_grp_keys
                else np.full(n_obs, "all", dtype=object)
            )
            label_col = next((c for c in _LABEL_COLS if c in obs_grp_keys), None)
            current_labels = _h5_obs_col(f, label_col, default="") if label_col else None
            score_col = next((c for c in _SCORE_COLS if c in obs_grp_keys), None)
            current_scores = np.asarray(_h5_obs_col(f, score_col), dtype=float) if score_col else None
            sample_id_arr = _h5_obs_col(f, "sample_id", default="") if "sample_id" in obs_grp_keys else None
            region_arr = _h5_obs_col(f, "region", default="") if "region" in obs_grp_keys else None
            lineage_arr = _h5_obs_col(f, "lineage", default="") if "lineage" in obs_grp_keys else None
            has_spatial = "obsm" in f and "spatial" in f["obsm"]
            spatial_coords = _h5_obsm(f, "spatial")[:, :2] if has_spatial else None
            obs_names_arr = _h5_obs_names(f)

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
        displayed_highlight = highlight_mask[indices]
        points = []
        for obs_idx in indices.tolist():
            score_val = float(current_scores[obs_idx]) if current_scores is not None else np.nan
            label_val = str(current_labels[obs_idx]) if current_labels is not None else ""
            points.append({
                "index": int(obs_idx),
                "obs_name": str(obs_names_arr[obs_idx]),
                "cell_id": str(cell_ids[obs_idx]),
                "x": float(coords[obs_idx, 0]),
                "y": float(coords[obs_idx, 1]),
                "cluster": str(clusters[obs_idx]),
                "sample_id": str(sample_id_arr[obs_idx]) if sample_id_arr is not None else None,
                "region": str(region_arr[obs_idx]) if region_arr is not None else None,
                "lineage": str(lineage_arr[obs_idx]) if lineage_arr is not None else None,
                "current_label": label_val if label_val else None,
                "current_score": None if np.isnan(score_val) else score_val,
                "gene_expression": None,
                "sx": float(spatial_coords[obs_idx, 0]) if spatial_coords is not None else None,
                "sy": float(spatial_coords[obs_idx, 1]) if spatial_coords is not None else None,
                "is_highlighted": bool(highlight_mask[obs_idx]),
            })
        view_token = f"{record.object_id}:{hash(indices.tobytes())}"
        self._view_indices[view_token] = indices
        return {
            "object_id": record.object_id,
            "points": points,
            "embedding_key": embedding_key,
            "cluster_key": cluster_key,
            "gene_name": None,
            "total_cells": int(n_obs),
            "displayed_cells": int(indices.size),
            "highlighted_total": int(highlight_mask.sum()),
            "highlighted_displayed": int(displayed_highlight.sum()),
            "view_token": view_token,
        }

    def get_combined_global_umap_points(
        self,
        global_record: ObjectRecord,
        lineage_records: list[ObjectRecord],
        embedding_key: str,
        cluster_key: str | None,
        max_points: int,
        min_per_cluster: int,
        max_per_cluster: int,
        random_seed: int,
    ) -> dict[str, Any]:
        """Build the global view from the union of each lineage object's own sampled
        subset, rather than sampling directly from the global object. Each lineage
        contributes an equal share of `max_points`, stratified by its own cluster
        labels; the resulting cell_ids are then matched back to their rows in the
        global object (which holds the shared embedding all lineages are plotted in).
        """
        _LABEL_COLS = ("reannot_display_label", "reannot_label", "current_label", "celltypist_label")
        _SCORE_COLS = ("reannot_confidence", "current_score", "celltypist_confidence")

        valid_records = [r for r in lineage_records if r.is_valid]
        per_lineage_quota = max(1, int(max_points) // max(1, len(valid_records)))

        combined_cell_ids: list[np.ndarray] = []
        for record in valid_records:
            try:
                with h5py.File(record.object_path, "r") as f:
                    n_obs = _h5_n_obs(f)
                    if n_obs == 0:
                        continue
                    obs_cols = _h5_obs_col_names(f)
                    candidates = _h5_cluster_key_candidates(f, obs_cols)
                    lineage_cluster_key = next(
                        (c for c in ("reannot_label", *candidates) if c in obs_cols), None
                    )
                    cluster_values = (
                        _h5_obs_col(f, lineage_cluster_key, default="all")
                        if lineage_cluster_key
                        else np.full(n_obs, "all", dtype=object)
                    )
                cell_ids = self._get_cell_ids(record)
                indices = stratified_sample_indices(
                    labels=cluster_values.astype(str),
                    max_points=per_lineage_quota,
                    min_per_cluster=min_per_cluster,
                    max_per_cluster=max_per_cluster if max_per_cluster > 0 else None,
                    random_seed=random_seed,
                )
                combined_cell_ids.append(cell_ids[indices])
            except Exception:
                # Skip lineage objects that can't be sampled rather than failing the whole view.
                continue

        combined_ids = (
            np.concatenate(combined_cell_ids) if combined_cell_ids else np.array([], dtype=object)
        )

        with h5py.File(global_record.object_path, "r") as f:
            coords = _h5_obsm(f, embedding_key)[:, :2]
            n_obs = coords.shape[0]
            obs_grp_keys = set(f["obs"].keys())
            global_cell_ids = self._get_cell_ids(global_record)
            clusters = (
                _h5_obs_col(f, cluster_key, default="all")
                if cluster_key and cluster_key in obs_grp_keys
                else np.full(n_obs, "all", dtype=object)
            )
            label_col = next((c for c in _LABEL_COLS if c in obs_grp_keys), None)
            current_labels = _h5_obs_col(f, label_col, default="") if label_col else None
            score_col = next((c for c in _SCORE_COLS if c in obs_grp_keys), None)
            current_scores = np.asarray(_h5_obs_col(f, score_col), dtype=float) if score_col else None
            sample_id_arr = _h5_obs_col(f, "sample_id", default="") if "sample_id" in obs_grp_keys else None
            region_arr = _h5_obs_col(f, "region", default="") if "region" in obs_grp_keys else None
            lineage_arr = _h5_obs_col(f, "lineage", default="") if "lineage" in obs_grp_keys else None
            has_spatial = "obsm" in f and "spatial" in f["obsm"]
            spatial_coords = _h5_obsm(f, "spatial")[:, :2] if has_spatial else None
            obs_names_arr = _h5_obs_names(f)

        # cell_id -> global row-index lookup. cell_id is not guaranteed unique in the
        # global object (e.g. reused barcodes across source samples), so map each id
        # to the position of its first occurrence rather than relying on a unique index.
        unique_ids, first_positions = np.unique(global_cell_ids, return_index=True)
        id_to_position = dict(zip(unique_ids.tolist(), first_positions.tolist()))
        matched = np.unique(np.array(
            [id_to_position[cid] for cid in combined_ids.tolist() if cid in id_to_position],
            dtype=int,
        )) if combined_ids.size else np.array([], dtype=int)

        points = []
        for obs_idx in matched.tolist():
            score_val = float(current_scores[obs_idx]) if current_scores is not None else np.nan
            label_val = str(current_labels[obs_idx]) if current_labels is not None else ""
            points.append({
                "index": int(obs_idx),
                "obs_name": str(obs_names_arr[obs_idx]),
                "cell_id": str(global_cell_ids[obs_idx]),
                "x": float(coords[obs_idx, 0]),
                "y": float(coords[obs_idx, 1]),
                "cluster": str(clusters[obs_idx]),
                "sample_id": str(sample_id_arr[obs_idx]) if sample_id_arr is not None else None,
                "region": str(region_arr[obs_idx]) if region_arr is not None else None,
                "lineage": str(lineage_arr[obs_idx]) if lineage_arr is not None else None,
                "current_label": label_val if label_val else None,
                "current_score": None if np.isnan(score_val) else score_val,
                "gene_expression": None,
                "sx": float(spatial_coords[obs_idx, 0]) if spatial_coords is not None else None,
                "sy": float(spatial_coords[obs_idx, 1]) if spatial_coords is not None else None,
            })
        view_token = f"{global_record.object_id}:{hash(matched.tobytes())}"
        self._view_indices[view_token] = matched
        return {
            "object_id": global_record.object_id,
            "points": points,
            "embedding_key": embedding_key,
            "cluster_key": cluster_key,
            "gene_name": None,
            "total_cells": int(n_obs),
            "displayed_cells": int(matched.size),
            "view_token": view_token,
        }

    def get_gene_catalog(self, record: ObjectRecord) -> dict[str, Any]:
        with h5py.File(record.object_path, "r") as f:
            genes = _h5_var_names(f)
        return {
            "object_id": record.object_id,
            "object_path": str(record.object_path),
            "genes": [str(g) for g in genes.tolist()],
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

    def _ensure_view_submatrix(self, record: ObjectRecord, view_token: str, index_array: np.ndarray) -> None:
        """Build (or reuse) the cached per-view CSC submatrix for `view_token`.

        Guarded by a lock since this mutates the single shared cache slot and can
        now be triggered either lazily (first gene request) or eagerly via
        `prewarm_view_submatrix` from a background task right after a view loads.
        """
        with self._view_submatrix_lock:
            if self._view_submatrix_token == view_token:
                return
            self._view_submatrix_token = view_token
            self._view_submatrix_data = None
            with h5py.File(record.object_path, "r") as f:
                self._view_submatrix_data = _h5_build_view_submatrix(f, index_array)

    def prewarm_view_submatrix(self, record: ObjectRecord, view_token: str) -> None:
        """Eagerly build the gene-expression submatrix for a just-loaded view.

        Scheduled as a background task right after /umap responds, so the
        multi-second submatrix build (dominated by two large h5py fancy-index
        reads) usually finishes while the user is still looking at the plot,
        before they pick a gene to color by.
        """
        index_array = self._view_indices.get(view_token)
        if index_array is None or index_array.size == 0:
            return
        try:
            self._ensure_view_submatrix(record, view_token, index_array)
        except Exception:
            # Best-effort — the lazy path in get_gene_expression_values will retry.
            pass

    def get_gene_expression_values(
        self,
        record: ObjectRecord,
        gene_name: str,
        indices: list[int],
        view_token: str | None = None,
    ) -> dict[str, Any]:
        # Prefer view_token lookup (no large payload) over caller-supplied indices.
        if view_token and view_token in self._view_indices:
            index_array = self._view_indices[view_token]
        else:
            index_array = np.asarray(indices, dtype=int)
            view_token = None  # token was unknown; fall back to index-based response

        if index_array.size == 0:
            return {"object_id": record.object_id, "gene_name": gene_name, "values": [], "ordered_values": []}

        # --- Fast path: use pre-built CSC submatrix (all genes, sampled cells) ---
        # The submatrix is built once per view on the first gene request, then all
        # subsequent gene queries are instant column extractions (no h5py I/O).
        if view_token:
            self._ensure_view_submatrix(record, view_token, index_array)

            if self._view_submatrix_data is not None:
                matrix, var_names = self._view_submatrix_data
                matches = np.where(var_names == gene_name)[0]
                if len(matches) == 0:
                    raise ValueError(f"Gene not found in object: {gene_name}")
                col = matrix[:, int(matches[0])]
                values = np.asarray(col.todense(), dtype=float).ravel()
                return {
                    "object_id": record.object_id,
                    "gene_name": gene_name,
                    "values": [],
                    "ordered_values": values.tolist(),
                }

        # --- Fallback path: per-gene h5py read with gene-level cache ---
        slot = f"{record.object_id}:{hash(index_array.tobytes())}"
        if self._gene_expr_cache_slot != slot:
            self._gene_expr_cache.clear()
            self._gene_expr_cache_slot = slot

        cache_key = f"{slot}:{gene_name}"
        if cache_key not in self._gene_expr_cache:
            with h5py.File(record.object_path, "r") as f:
                n_obs = _h5_n_obs(f)
                if int(index_array.min()) < 0 or int(index_array.max()) >= n_obs:
                    raise ValueError("Requested point indices are out of bounds for the current object.")
                vals = _h5_gene_expression_for_indices(f, gene_name, index_array)
            self._gene_expr_cache[cache_key] = vals if vals is not None else np.zeros(len(index_array), dtype=float)

        values = self._gene_expr_cache[cache_key]

        if view_token:
            return {
                "object_id": record.object_id,
                "gene_name": gene_name,
                "values": [],
                "ordered_values": values.tolist(),
            }
        return {
            "object_id": record.object_id,
            "gene_name": gene_name,
            "values": [
                {"index": int(idx), "value": float(val)}
                for idx, val in zip(index_array.tolist(), values.tolist(), strict=False)
            ],
            "ordered_values": None,
        }

    def get_point_cluster_values(
        self,
        record: ObjectRecord,
        cluster_key: str,
        indices: list[int],
    ) -> dict[str, Any]:
        index_array = np.asarray(indices, dtype=int)
        if index_array.size == 0:
            return {"object_id": record.object_id, "cluster_key": cluster_key, "values": []}
        with h5py.File(record.object_path, "r") as f:
            if cluster_key not in f["obs"]:
                raise ValueError(f"Cluster key not found in obs: {cluster_key}")
            n_obs = _h5_n_obs(f)
            if int(index_array.min()) < 0 or int(index_array.max()) >= n_obs:
                raise ValueError("Requested point indices are out of bounds for the current object.")
            cluster_values = _h5_obs_col(f, cluster_key, default="NA")[index_array]
        return {
            "object_id": record.object_id,
            "cluster_key": cluster_key,
            "values": [
                {"index": int(idx), "cluster": str(clus)}
                for idx, clus in zip(index_array.tolist(), cluster_values.tolist(), strict=False)
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

        self._record_latest_object_change_snapshot(
            records=[record],
            change_type="reference_propagation",
            description=f"Reference-based propagation on {record.lineage_name} into {label_key}.",
        )
        try:
            self._write_object(record, adata, prefix=f"{record.object_path.stem}_{suffix}_refknn_")
        except Exception:
            self._clear_latest_object_change_snapshot()
            raise
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
        with h5py.File(record.object_path, "r") as f:
            if cluster_key not in f["obs"]:
                raise ValueError(f"Cluster key not found in obs: {cluster_key}")
            cluster_values = _h5_obs_col(f, cluster_key, default="NA")
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

        self._record_latest_object_change_snapshot(
            records=[source_record, destination_record],
            change_type="move_cluster",
            description=(
                f"Move cluster {cluster_id} from {source_record.lineage_name} "
                f"to {destination_record.lineage_name}."
            ),
        )
        self._record_latest_move_snapshot(
            source_record=source_record,
            destination_record=destination_record,
            preview=preview,
        )
        try:
            remaining = self.recompute_embeddings(
                remaining,
                f"{source_record.lineage_name} after moving cluster {cluster_id}",
            )
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
                raise
            self._commit_staged_object(source_record, remaining, source_temp_path)
            self._commit_staged_object(destination_record, combined, destination_temp_path)
        except Exception:
            local_source_temp = locals().get("source_temp_path")
            local_destination_temp = locals().get("destination_temp_path")
            if isinstance(local_source_temp, Path):
                local_source_temp.unlink(missing_ok=True)
            if isinstance(local_destination_temp, Path):
                local_destination_temp.unlink(missing_ok=True)
            self._clear_latest_object_change_snapshot()
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
        with h5py.File(record.object_path, "r") as f:
            coords = _h5_obsm(f, embedding_key)[:, :2]
            n_obs = coords.shape[0]
            obs_cols = _h5_obs_col_names(f)
            obs_grp_keys = set(f["obs"].keys())
            cluster_values = (
                _h5_obs_col(f, cluster_key, default="all")
                if cluster_key and cluster_key in obs_grp_keys
                else np.full(n_obs, "all", dtype=object)
            )
            cell_ids_arr = (
                _h5_obs_col(f, "cell_id")
                if "cell_id" in obs_cols
                else _h5_obs_names(f)
            )

        selected_mask = np.zeros(n_obs, dtype=bool)
        polygon_summaries: list[dict[str, Any]] = []
        for polygon in polygons:
            polygon_mask = points_in_polygon(coords, np.asarray(polygon["vertices"], dtype=float))
            selected_mask |= polygon_mask
            cluster_counts = pd.Series(cluster_values[polygon_mask]).value_counts().sort_index()
            polygon_summaries.append({
                "polygon_id": polygon["polygon_id"],
                "n_cells": int(polygon_mask.sum()),
                "clusters": [
                    {"cluster": str(cluster), "n_cells": int(count)}
                    for cluster, count in cluster_counts.items()
                ],
            })

        selected_indices = np.flatnonzero(selected_mask)
        return {
            "total_selected_cells": int(selected_indices.size),
            "selected_indices": selected_indices.tolist(),
            "selected_cell_ids": [str(cid) for cid in cell_ids_arr[selected_indices].tolist()],
            "polygon_summaries": polygon_summaries,
        }

    def get_features(self, record: ObjectRecord, pca_key: str = "X_pca_lineage") -> np.ndarray:
        with h5py.File(record.object_path, "r") as f:
            if "obsm" not in f:
                raise KeyError("No PCA embedding available in obsm.")
            obsm_keys = list(f["obsm"].keys())
            key = pca_key if pca_key in obsm_keys else next((k for k in obsm_keys if "pca" in k.lower()), None)
            if key is None:
                raise KeyError("No PCA embedding available in obsm.")
            return _h5_obsm(f, key).astype(float)

    def get_graph(self, record: ObjectRecord) -> sparse.spmatrix | None:
        with h5py.File(record.object_path, "r") as f:
            if "obsp" not in f or "lineage_connectivities" not in f["obsp"]:
                return None
            return _h5_obsp_sparse(f, "lineage_connectivities")

    def get_or_build_knn_graph(
        self, record: ObjectRecord, n_neighbors: int, pca_key: str = "X_pca_lineage"
    ) -> sparse.spmatrix:
        """Return the object's neighbor graph, building it at most once per session.

        Most lineage objects here have no precomputed `obsp/lineage_connectivities`,
        so without caching every propagate() call pays for a fresh brute-force KNN
        build over the full object (tens of seconds on the larger lineages). Since
        annotation workflows typically re-run propagation several times while tuning
        thresholds, caching the built graph in memory makes every call after the
        first instant.
        """
        precomputed = self.get_graph(record)
        if precomputed is not None:
            return precomputed
        cache_key = f"{record.object_id}:{n_neighbors}:{pca_key}"
        cached = self._graph_cache.get(cache_key)
        if cached is not None:
            return cached
        graph = build_knn_graph(self.get_features(record, pca_key=pca_key), n_neighbors)
        self._graph_cache[cache_key] = graph
        return graph

    def get_obs_for_propagation(
        self, record: ObjectRecord, cluster_key: str
    ) -> tuple[int, np.ndarray, np.ndarray, np.ndarray]:
        """Read (n_obs, obs_names, cluster_values, cell_ids) via h5py — X matrix never loaded."""
        with h5py.File(record.object_path, "r") as f:
            n_obs = _h5_n_obs(f)
            obs_names = _h5_obs_names(f)
            obs_cols = _h5_obs_col_names(f)
            cluster_values = (
                _h5_obs_col(f, cluster_key, default="NA")
                if cluster_key in obs_cols
                else np.full(n_obs, "all", dtype=object)
            )
            cell_ids = _h5_obs_col(f, "cell_id") if "cell_id" in obs_cols else obs_names
        return n_obs, obs_names, cluster_values, cell_ids

    def get_cluster_label_editor(self, record: ObjectRecord, cluster_key: str) -> dict[str, Any]:
        with h5py.File(record.object_path, "r") as f:
            if cluster_key not in f["obs"]:
                raise ValueError(f"Cluster key not found in obs: {cluster_key}")
            cluster_values = _h5_obs_col(f, cluster_key, default="NA")
            display_column = _display_column_name(cluster_key)
            existing_display = (
                _h5_obs_col(f, display_column, default="")
                if display_column in f["obs"]
                else np.full(len(cluster_values), "", dtype=object)
            )

        rows: list[dict[str, Any]] = []
        counts = pd.Series(cluster_values).value_counts(sort=False)
        ordered_cluster_ids = pd.Index(cluster_values).drop_duplicates().tolist()
        for cluster_id in ordered_cluster_ids:
            mask = cluster_values == cluster_id
            display_values = pd.Series(existing_display[mask]).replace("", pd.NA).dropna()
            display_name = str(display_values.iloc[0]) if not display_values.empty else None
            rows.append({
                "cluster_id": str(cluster_id),
                "n_cells": int(counts.loc[cluster_id]),
                "display_name": display_name,
            })

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
        # Renaming clusters only touches one obs column + a couple of uns entries —
        # loading the full object (including X) and rewriting the entire file to
        # disk costs tens of seconds on the larger lineages for a change that's a
        # few KB. Patch just the affected elements in place instead.
        with h5py.File(record.object_path, "r") as f:
            obs_cols = _h5_obs_col_names(f)
            if cluster_key not in obs_cols:
                raise ValueError(f"Cluster key not found in obs: {cluster_key}")
            cluster_values = _h5_obs_col(f, cluster_key, default="NA")
            existing_definitions = (
                dict(read_elem(f["uns"]["cluster_display_name_definitions"]))
                if "cluster_display_name_definitions" in f["uns"]
                else {}
            )

        display_column = display_column or _display_column_name(cluster_key)
        normalized_mapping = {str(key): value.strip() for key, value in mapping.items() if value.strip()}
        display_values = np.asarray(
            [normalized_mapping.get(str(cluster_id), str(cluster_id)) for cluster_id in cluster_values],
            dtype=object,
        )

        display_name_definitions = deepcopy(existing_definitions)
        display_name_definitions[str(cluster_key)] = normalized_mapping

        self._record_latest_object_change_snapshot(
            records=[record],
            change_type="cluster_label_names",
            description=f"Save cluster names on {record.lineage_name} for {cluster_key}.",
        )
        try:
            ad.settings.allow_write_nullable_strings = True
            with h5py.File(record.object_path, "r+") as f:
                if display_column in f["obs"]:
                    del f["obs"][display_column]
                write_elem(f["obs"], display_column, pd.array(display_values, dtype="string"))
                column_order = [str(c) for c in f["obs"].attrs.get("column-order", [])]
                if display_column not in column_order:
                    f["obs"].attrs["column-order"] = np.array(column_order + [display_column], dtype=object)

                if "cluster_display_name_definitions" in f["uns"]:
                    del f["uns"]["cluster_display_name_definitions"]
                write_elem(f["uns"], "cluster_display_name_definitions", display_name_definitions)

                if cluster_key == "reannot_label":
                    if "reannotation_label_definitions" in f["uns"]:
                        del f["uns"]["reannotation_label_definitions"]
                    write_elem(f["uns"], "reannotation_label_definitions", normalized_mapping)
            self.invalidate_cached(record.object_id)
        except Exception:
            self._clear_latest_object_change_snapshot()
            raise
        return {
            "object_id": record.object_id,
            "object_path": str(record.object_path),
            "cluster_key": cluster_key,
            "display_column": display_column,
            "n_updated": int(len(normalized_mapping)),
        }

    def save_propagation_results(self, record: ObjectRecord, session: SessionState) -> dict[str, Any]:
        """Write a completed propagation's per-cell labels into the object in place.

        Only touches obs columns + a handful of uns bookkeeping keys — X/obsm are
        never loaded, so this is a small, fast write regardless of object size
        (previously this loaded and rewrote the entire AnnData object, including
        the gene matrix, costing tens of seconds on the larger lineages)."""
        if session.last_propagation is None:
            raise ValueError("No propagated result is available to save.")
        result = session.last_propagation
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        with h5py.File(record.object_path, "r") as f:
            n_obs = _h5_n_obs(f)
            obs_cols = _h5_obs_col_names(f)
            cluster_values = (
                _h5_obs_col(f, result.cluster_key, default="NA")
                if result.cluster_key in obs_cols
                else np.full(n_obs, "all", dtype=object)
            )
            existing_history_raw = (
                read_elem(f["uns"]["reannotation_sessions"]) if "reannotation_sessions" in f["uns"] else {}
            )

        seed_mask = np.zeros(n_obs, dtype=bool)
        polygon_ids = np.full(n_obs, "", dtype=object)
        for index in session.seed_labels:
            seed_mask[index] = True
            polygon_ids[index] = ";".join(sorted(session.seed_polygon_ids.get(index, set())))

        label_definitions = dict(session.seed_display_names)
        display_labels = np.asarray(
            [label_definitions.get(str(label), str(label)) for label in result.assigned_labels],
            dtype=object,
        )

        save_manifest = {
            "session_id": session.session_id,
            "source_object": str(record.object_path),
            "saved_object": str(record.object_path),
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
        if isinstance(existing_history_raw, list):
            sessions_history = {
                str(index): value for index, value in enumerate(existing_history_raw) if isinstance(value, dict)
            }
        elif isinstance(existing_history_raw, dict):
            sessions_history = dict(existing_history_raw)
        else:
            # Legacy/unexpected uns encodings (e.g. a raw string-array) — discard rather than crash.
            sessions_history = {}
        sessions_history[timestamp] = save_manifest
        sessions_history_safe = _json_safe(sessions_history)
        save_manifest_safe = _json_safe(save_manifest)
        label_definitions_safe = _json_safe(label_definitions)

        obs_updates: dict[str, np.ndarray] = {
            "reannot_label": result.assigned_labels,
            "reannot_display_label": display_labels,
            "reannot_label_source": np.where(
                seed_mask, "polygon_seed", np.where(result.assigned_mask, result.method, "unassigned")
            ),
            "reannot_confidence": np.asarray(result.assigned_scores, dtype=float),
            "reannot_margin": np.asarray(result.assigned_margins, dtype=float),
            "reannot_seed": seed_mask,
            "reannot_polygon_ids": polygon_ids,
            "reannot_scope": np.repeat(result.scope, n_obs),
            "reannot_cluster_key": np.repeat(result.cluster_key, n_obs),
            "reannot_session_id": np.repeat(session.session_id, n_obs),
            "reannot_timestamp": np.repeat(timestamp, n_obs),
        }
        uns_updates = {
            "reannotation_sessions": sessions_history_safe,
            "reannotation_sessions_json": json.dumps(sessions_history_safe, indent=2),
            "reannotation_last_session": save_manifest_safe,
            "reannotation_label_definitions": label_definitions_safe,
            "reannotation_save_manifest": save_manifest_safe,
        }

        self._record_latest_object_change_snapshot(
            records=[record],
            change_type="save_reannotated_object",
            description=f"Save propagated reannotation fields on {record.lineage_name}.",
        )
        try:
            ad.settings.allow_write_nullable_strings = True
            with h5py.File(record.object_path, "r+") as f:
                for column, values in obs_updates.items():
                    _h5_write_obs_column(f, column, np.asarray(values))
                for key, value in uns_updates.items():
                    if key in f["uns"]:
                        del f["uns"][key]
                    write_elem(f["uns"], key, value)
            self.invalidate_cached(record.object_id)
        except Exception:
            self._clear_latest_object_change_snapshot()
            raise

        cluster_frame = pd.DataFrame(
            {
                "cluster": cluster_values,
                "predicted_label": result.assigned_labels,
                "assigned": result.assigned_mask,
                "score": result.assigned_scores,
            }
        )
        cluster_summary = []
        for cluster, group in cluster_frame.groupby("cluster", sort=True):
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

        return {"object_path": record.object_path, "cluster_summary": cluster_summary}

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

        self._record_latest_object_change_snapshot(
            records=[record],
            change_type="promote_reannot_label",
            description=f"Promote reannot_label_new to canonical labels on {record.lineage_name}.",
        )
        try:
            self._write_object(record, adata, prefix=f"{record.object_path.stem}_promote_new_")
        except Exception:
            self._clear_latest_object_change_snapshot()
            raise
        return {
            "object_id": record.object_id,
            "object_path": str(record.object_path),
            "source_label_key": source_label_key,
            "source_display_key": source_display_key,
            "target_label_key": target_label_key,
            "target_display_key": target_display_key,
        }

    # F-04 / F-13 — Obs metadata coloring and QC

    _QC_COLUMNS = {
        "n_genes_by_counts",
        "total_counts",
        "pct_counts_mt",
        "pct_counts_ribo",
        "pct_counts_hb",
        "doublet_score",
        "predicted_doublet",
        "log1p_total_counts",
        "log1p_n_genes_by_counts",
        "n_counts",
        "n_genes",
        "percent_mito",
        "percent_ribo",
    }

    def get_obs_columns(self, record: ObjectRecord) -> dict[str, Any]:
        with h5py.File(record.object_path, "r") as f:
            obs_cols = _h5_obs_col_names(f)
            obs_grp = f["obs"]
            columns = []
            for col in obs_cols:
                if col not in obs_grp:
                    continue
                item = obs_grp[col]
                if isinstance(item, h5py.Group):
                    n_cats = _h5_category_count(item) if "categories" in item else 0
                    columns.append({
                        "name": col,
                        "dtype": "categorical",
                        "is_numeric": False,
                        "is_qc": col in self._QC_COLUMNS,
                        "n_unique": n_cats,
                    })
                else:
                    is_numeric = item.dtype.kind in ("f", "i", "u", "b")
                    dtype = "float" if item.dtype.kind == "f" else ("int" if is_numeric else "categorical")
                    columns.append({
                        "name": col,
                        "dtype": dtype,
                        "is_numeric": is_numeric,
                        "is_qc": col in self._QC_COLUMNS,
                        "n_unique": None,
                    })
        return {"object_id": record.object_id, "columns": columns}

    def get_obs_values(self, record: ObjectRecord, column: str, indices: list[int]) -> dict[str, Any]:
        with h5py.File(record.object_path, "r") as f:
            if column not in f["obs"]:
                raise ValueError(f"Column '{column}' not found in obs.")
            is_numeric = _h5_obs_col_is_numeric(f, column)
            dtype = "float" if (is_numeric and f["obs"][column].dtype.kind == "f") else ("int" if is_numeric else "categorical")
            col_data = _h5_obs_col(f, column)
        idx_arr = np.asarray(indices, dtype=int)
        values = []
        for obs_idx in idx_arr.tolist():
            raw = col_data[obs_idx]
            if is_numeric:
                v: float | str | None = None if (isinstance(raw, float) and np.isnan(raw)) else float(raw)
            else:
                raw_str = str(raw) if raw is not None else ""
                v = None if raw_str == "" else raw_str
            values.append({"index": int(obs_idx), "value": v})
        return {"object_id": record.object_id, "column": column, "dtype": dtype, "is_numeric": is_numeric, "values": values}

    # F-06 — Spatial transcriptomics: spatial coords added in _point_payload

    def _has_spatial(self, adata: ad.AnnData) -> bool:
        return "spatial" in adata.obsm

    # F-08 — Differential expression

    def run_de_analysis(
        self,
        record: ObjectRecord,
        cluster_key: str,
        target_clusters: list[str],
        reference_clusters: list[str],
        top_n: int = 50,
        method: str = "wilcoxon",
    ) -> dict[str, Any]:
        adata = self.get_adata(record)
        if cluster_key not in adata.obs.columns:
            raise ValueError(f"Cluster key '{cluster_key}' not found.")

        labels = _obs_to_str_array(adata.obs, cluster_key)
        target_mask = np.isin(labels, target_clusters)
        reference_mask = np.isin(labels, reference_clusters) if reference_clusters else ~target_mask
        n_target = int(target_mask.sum())
        n_reference = int(reference_mask.sum())

        if n_target == 0:
            raise ValueError("No cells found in target clusters.")
        if n_reference == 0:
            raise ValueError("No cells found in reference clusters.")

        from scipy import sparse as sp
        from scipy.stats import rankdata

        X = adata.X
        if sp.issparse(X):
            X_target = np.asarray(X[target_mask].todense())
            X_ref = np.asarray(X[reference_mask].todense())
        else:
            X_target = np.asarray(X[target_mask])
            X_ref = np.asarray(X[reference_mask])

        mean_target = X_target.mean(axis=0)
        mean_ref = X_ref.mean(axis=0)
        lfc = np.log2(mean_target + 1e-9) - np.log2(mean_ref + 1e-9)

        n_genes = X_target.shape[1]
        n1 = X_target.shape[0]
        n2 = X_ref.shape[0]
        p_vals = np.ones(n_genes)

        if method == "wilcoxon":
            # Vectorized Mann-Whitney U via rank-sum — O(n_genes * (n1+n2)*log(n1+n2))
            # rather than calling mannwhitneyu per gene in a Python loop
            combined = np.vstack([X_target, X_ref])  # (n1+n2, n_genes)
            # rank each gene column independently
            from scipy.stats import rankdata as _rankdata
            for g in range(n_genes):
                col = combined[:, g]
                if col.std() == 0:
                    continue
                ranks = _rankdata(col)
                U1 = np.sum(ranks[:n1]) - n1 * (n1 + 1) / 2
                U2 = n1 * n2 - U1
                U = min(U1, U2)
                mu = n1 * n2 / 2.0
                sigma = np.sqrt(n1 * n2 * (n1 + n2 + 1) / 12.0)
                if sigma == 0:
                    continue
                z = (U - mu) / sigma
                from scipy.stats import norm as _norm
                p_vals[g] = 2 * _norm.sf(abs(z))
        else:
            # Vectorized Welch t-test across all genes at once
            var_t = X_target.var(axis=0, ddof=1)
            var_r = X_ref.var(axis=0, ddof=1)
            se = np.sqrt(var_t / n1 + var_r / n2)
            with np.errstate(divide='ignore', invalid='ignore'):
                t_stat = np.where(se > 0, (mean_target - mean_ref) / se, 0.0)
            # Welch-Satterthwaite df
            num = (var_t / n1 + var_r / n2) ** 2
            denom = (var_t / n1) ** 2 / (n1 - 1) + (var_r / n2) ** 2 / (n2 - 1)
            with np.errstate(divide='ignore', invalid='ignore'):
                df = np.where(denom > 0, num / denom, 1.0)
            df = np.maximum(df, 1.0)
            from scipy.stats import t as _t_dist
            p_vals = 2 * _t_dist.sf(np.abs(t_stat), df)
            p_vals = np.nan_to_num(p_vals, nan=1.0)

        from statsmodels.stats.multitest import multipletests
        try:
            _, p_adj, _, _ = multipletests(p_vals, method="fdr_bh")
        except Exception:
            p_adj = p_vals.copy()

        gene_names = list(adata.var_names)
        order = np.argsort(p_adj)[:top_n]
        genes = [
            {
                "gene_name": str(gene_names[g]),
                "log_fold_change": float(lfc[g]),
                "p_val": float(p_vals[g]),
                "p_val_adj": float(p_adj[g]),
                "mean_target": float(mean_target[g]),
                "mean_reference": float(mean_ref[g]),
            }
            for g in order
        ]
        return {
            "object_id": record.object_id,
            "cluster_key": cluster_key,
            "target_clusters": target_clusters,
            "reference_clusters": reference_clusters if reference_clusters else list({str(l) for l in labels[reference_mask].tolist()}),
            "n_target_cells": n_target,
            "n_reference_cells": n_reference,
            "method": method,
            "genes": genes,
        }

    # F-09 — Annotation export

    def export_annotations(
        self,
        record: ObjectRecord,
        session_state: Any,
        fmt: str = "csv",
    ) -> tuple[str, str]:
        """Return (content_string, mime_type) for export."""
        adata = self.get_adata(record)
        cell_ids = self._get_cell_ids(record)

        if session_state is not None and session_state.last_propagation is not None:
            result = session_state.last_propagation
            label_defs = dict(session_state.seed_display_names)
            assigned_labels = result.assigned_labels
            scores = result.assigned_scores
            margins = result.assigned_margins
            assigned_mask = result.assigned_mask
            seed_mask_arr = np.zeros(adata.n_obs, dtype=bool)
            for idx in session_state.seed_labels:
                if 0 <= idx < adata.n_obs:
                    seed_mask_arr[idx] = True
            display_labels = np.asarray(
                [label_defs.get(str(l), str(l)) for l in assigned_labels],
                dtype=object,
            )
        elif "reannot_label" in adata.obs.columns:
            assigned_labels = _obs_to_str_array(adata.obs, "reannot_label")
            display_labels = _obs_to_str_array(adata.obs, "reannot_display_label") if "reannot_display_label" in adata.obs.columns else assigned_labels
            _s = _obs_to_float_array(adata.obs, "reannot_confidence")
            scores = _s if _s is not None else np.full(adata.n_obs, np.nan)
            _m = _obs_to_float_array(adata.obs, "reannot_margin")
            margins = _m if _m is not None else np.full(adata.n_obs, np.nan)
            assigned_mask = assigned_labels != ""
            seed_mask_arr = np.zeros(adata.n_obs, dtype=bool)
            if "reannot_seed" in adata.obs.columns:
                seed_mask_arr = adata.obs["reannot_seed"].to_numpy(dtype=bool)
        else:
            raise ValueError("No annotation available in session or saved to object.")

        rows = []
        for i in range(adata.n_obs):
            rows.append({
                "cell_barcode": str(cell_ids[i]),
                "obs_name": str(adata.obs_names[i]),
                "annotation_label": str(assigned_labels[i]) if assigned_mask[i] else "",
                "display_label": str(display_labels[i]) if assigned_mask[i] else "",
                "confidence_score": float(scores[i]) if not np.isnan(scores[i]) else None,
                "margin": float(margins[i]) if not np.isnan(margins[i]) else None,
                "is_annotated": bool(assigned_mask[i]),
                "is_seed": bool(seed_mask_arr[i]),
            })

        df = pd.DataFrame(rows)
        if fmt == "csv":
            content = df.to_csv(index=False)
            mime = "text/csv"
        elif fmt == "tsv":
            content = df.to_csv(index=False, sep="\t")
            mime = "text/tab-separated-values"
        else:
            import json as _json
            content = _json.dumps(rows, default=lambda x: None if pd.isna(x) else x, indent=2)
            mime = "application/json"
        return content, mime

    # F-10 — Annotation coverage

    def get_annotation_coverage(self, record: ObjectRecord) -> dict[str, Any]:
        try:
            with h5py.File(record.object_path, "r") as f:
                obs_cols = _h5_obs_col_names(f)
                n_obs = _h5_n_obs(f)
                obs_grp = f["obs"]
                annotation_col = next(
                    (col for col in ("reannot_label", "reannot_display_label") if col in obs_grp),
                    None,
                )
                if annotation_col:
                    labels = _h5_obs_col(f, annotation_col, default="")
                    annotated = int((labels != "").sum())
                    frac = float(annotated / n_obs) if n_obs > 0 else 0.0
                else:
                    annotated = None
                    frac = None
                cluster_keys = _h5_cluster_key_candidates(f, obs_cols)
                default_cluster = cluster_keys[0] if cluster_keys else None
                n_clusters = None
                if default_cluster and default_cluster in obs_grp:
                    item = obs_grp[default_cluster]
                    if isinstance(item, h5py.Group) and "categories" in item:
                        n_clusters = _h5_category_count(item)
                    elif isinstance(item, h5py.Dataset):
                        n_clusters = int(len(np.unique(item[:])))
        except Exception:
            return {
                "object_id": record.object_id,
                "lineage_name": record.lineage_name,
                "n_cells": record.n_cells,
                "n_annotated": None,
                "annotation_fraction": None,
                "annotation_column": None,
                "n_clusters": None,
            }
        return {
            "object_id": record.object_id,
            "lineage_name": record.lineage_name,
            "n_cells": int(n_obs),
            "n_annotated": annotated,
            "annotation_fraction": frac,
            "annotation_column": annotation_col,
            "n_clusters": n_clusters,
        }

    # F-15 — Annotation diff

    def compare_cluster_columns(
        self,
        record: ObjectRecord,
        key_a: str,
        key_b: str,
    ) -> dict[str, Any]:
        with h5py.File(record.object_path, "r") as f:
            for key in (key_a, key_b):
                if key not in f["obs"]:
                    raise ValueError(f"Column '{key}' not found in obs.")
            labels_a = _h5_obs_col(f, key_a, default="").astype(str)
            labels_b = _h5_obs_col(f, key_b, default="").astype(str)
            n_obs = len(labels_a)
        changed = labels_a != labels_b
        changed_indices = np.flatnonzero(changed).tolist()
        pairs = pd.DataFrame({"a": labels_a, "b": labels_b})
        transition_counts = pairs.groupby(["a", "b"]).size().reset_index(name="count")
        transitions = [
            {"label_a": str(row["a"]), "label_b": str(row["b"]), "count": int(row["count"])}
            for _, row in transition_counts.iterrows()
        ]
        return {
            "object_id": record.object_id,
            "key_a": key_a,
            "key_b": key_b,
            "total_cells": int(n_obs),
            "changed_cells": int(changed.sum()),
            "unchanged_cells": int((~changed).sum()),
            "transitions": transitions,
            "changed_indices": [int(i) for i in changed_indices],
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
