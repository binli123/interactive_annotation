from __future__ import annotations

import base64
import io
import os
from collections import OrderedDict
from copy import deepcopy
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
from app.services.sampling import stratified_sample_indices


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

    def _touch(self, object_id: str, adata: ad.AnnData) -> ad.AnnData:
        self._cache[object_id] = adata
        self._cache.move_to_end(object_id)
        while len(self._cache) > self.max_cached_objects:
            _, evicted = self._cache.popitem(last=False)
            if getattr(evicted, "isbacked", False):
                evicted.file.close()
        return adata

    def replace_cached(self, object_id: str, adata: ad.AnnData) -> ad.AnnData:
        cached = self._cache.pop(object_id, None)
        if cached is not None and getattr(cached, "isbacked", False):
            cached.file.close()
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

    def get_umap_points(
        self,
        record: ObjectRecord,
        embedding_key: str,
        cluster_key: str | None,
        gene_name: str | None,
        max_points: int,
        min_per_cluster: int,
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
            random_seed=random_seed,
        )
        obs_frame = adata.obs.iloc[indices]
        if "cell_id" in adata.obs.columns:
            cell_ids = _obs_to_str_array(adata.obs, "cell_id")[indices]
        else:
            cell_ids = adata.obs_names.to_numpy(dtype=object)[indices]

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
            points.append(
                {
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
            )

        return {
            "object_id": record.object_id,
            "embedding_key": embedding_key,
            "cluster_key": cluster_key,
            "gene_name": gene_name,
            "total_cells": int(adata.n_obs),
            "displayed_cells": int(indices.size),
            "points": points,
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
        for cluster_id in sorted(counts.index.tolist(), key=lambda value: str(value)):
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
            temp_path.replace(record.object_path)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

        self.replace_cached(record.object_id, adata)


adata_service = AnnDataService()
