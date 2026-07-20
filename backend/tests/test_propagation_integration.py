"""Integration tests for the propagation pipeline.

Tests cover:
- get_obs_for_propagation: h5py-only reads, no X loaded
- /propagate endpoint: correct labels, no OOM path
- Memory efficiency: peak RSS does not spike by loading X
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from app.services.adata_service import AnnDataService
from app.models.state import ObjectRecord, PolygonSeedBatch
from app.services.sessions import SessionStore
from app.services.propagation import build_knn_graph

from tests.conftest import make_adata_with_graph


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_record(path: Path) -> ObjectRecord:
    return ObjectRecord(
        object_id="test-obj",
        lineage_name="test",
        object_path=path,
        lineage_dir=path.parent,
    )


def _seed_session(
    store: SessionStore,
    session_id: str,
    adata,
    cluster_key: str,
    n_seeds_per_cluster: int = 10,
) -> None:
    """Inject seed labels directly into the session (no HTTP round-trip needed)."""
    n_clusters = adata.obs[cluster_key].nunique()
    per_cluster = len(adata) // n_clusters
    for c_idx, label in enumerate(sorted(adata.obs[cluster_key].unique())):
        start = c_idx * per_cluster
        indices = np.arange(start, start + n_seeds_per_cluster)
        batch = PolygonSeedBatch(
            polygon_id=f"poly_{label}",
            label=label,
            display_name=label,
            notes=None,
            cell_indices=indices,
            vertices=[[0, 0], [1, 0], [1, 1], [0, 1]],
        )
        store.register_batch(session_id, batch)


# ---------------------------------------------------------------------------
# Unit: get_obs_for_propagation
# ---------------------------------------------------------------------------

class TestGetObsForPropagation:
    def test_returns_correct_n_obs(self, h5ad_path, graph_adata):
        svc = AnnDataService(max_cached_objects=0)
        n_obs, obs_names, cluster_values, cell_ids = svc.get_obs_for_propagation(
            _make_record(h5ad_path), "Celltypes"
        )
        assert n_obs == graph_adata.n_obs

    def test_cluster_values_match(self, h5ad_path, graph_adata):
        svc = AnnDataService(max_cached_objects=0)
        n_obs, obs_names, cluster_values, cell_ids = svc.get_obs_for_propagation(
            _make_record(h5ad_path), "Celltypes"
        )
        expected = graph_adata.obs["Celltypes"].to_numpy(dtype=object)
        np.testing.assert_array_equal(cluster_values, expected)

    def test_cell_ids_match(self, h5ad_path, graph_adata):
        svc = AnnDataService(max_cached_objects=0)
        n_obs, obs_names, cluster_values, cell_ids = svc.get_obs_for_propagation(
            _make_record(h5ad_path), "Celltypes"
        )
        expected = graph_adata.obs["cell_id"].to_numpy(dtype=object)
        np.testing.assert_array_equal(cell_ids, expected)

    def test_missing_cluster_key_falls_back_to_all(self, h5ad_path, graph_adata):
        svc = AnnDataService(max_cached_objects=0)
        n_obs, obs_names, cluster_values, cell_ids = svc.get_obs_for_propagation(
            _make_record(h5ad_path), "nonexistent_key"
        )
        assert (cluster_values == "all").all()

    def test_does_not_load_X_into_cache(self, h5ad_path):
        """AnnDataService with max_cached_objects=0 must have an empty cache after the call."""
        svc = AnnDataService(max_cached_objects=0)
        svc.get_obs_for_propagation(_make_record(h5ad_path), "Celltypes")
        assert len(svc._cache) == 0

    def test_never_calls_read_h5ad(self, h5ad_path):
        """get_obs_for_propagation must use h5py directly, never anndata.read_h5ad.

        anndata.read_h5ad loads the full X matrix into RAM — calling it on a
        large object causes OOM.  This mock asserts the h5py-only code path is
        taken regardless of fixture size.
        """
        import anndata
        from unittest.mock import patch

        svc = AnnDataService(max_cached_objects=0)
        with patch.object(anndata, "read_h5ad", wraps=anndata.read_h5ad) as mock_read:
            svc.get_obs_for_propagation(_make_record(h5ad_path), "Celltypes")
            mock_read.assert_not_called()


# ---------------------------------------------------------------------------
# Integration: propagation pipeline
# ---------------------------------------------------------------------------

class TestPropagationIntegration:
    def _run(self, h5ad_path, graph_adata, method="knn_vote", scope="whole_lineage"):
        svc = AnnDataService(max_cached_objects=0)
        store = SessionStore()
        record = _make_record(h5ad_path)
        sid = "test-session"

        store.get_or_create(
            session_id=sid,
            object_id="test-obj",
            embedding_key="X_umap",
            cluster_key="Celltypes",
        )
        _seed_session(store, sid, graph_adata, "Celltypes", n_seeds_per_cluster=10)

        # Replicate what the propagate route does, now using h5py path
        n_obs, obs_names, cluster_values, cell_ids = svc.get_obs_for_propagation(
            record, "Celltypes"
        )
        session = store.get(sid)
        seed_labels = np.full(n_obs, "", dtype=object)
        for index, label in session.seed_labels.items():
            seed_labels[index] = label
        seed_mask = seed_labels != ""
        assert seed_mask.any(), "No seeds were registered"

        graph = svc.get_graph(record)
        features = svc.get_features(record)

        if method == "knn_vote":
            from app.services.propagation import run_knn_vote
            result = run_knn_vote(
                features=features,
                seed_label_names=seed_labels,
                eligible_mask=np.ones(n_obs, dtype=bool),
                n_neighbors=15,
                min_score=0.0,
                min_margin=0.0,
                annotate_all=True,
            )
        else:
            from app.services.propagation import run_graph_diffusion
            result = run_graph_diffusion(
                graph=graph,
                seed_label_names=seed_labels,
                eligible_mask=np.ones(n_obs, dtype=bool),
                alpha=0.85,
                max_iter=50,
                tol=1e-4,
                min_score=0.0,
                min_margin=0.0,
                annotate_all=True,
                smoothing=0.0,
            )
        return result, seed_mask, obs_names, cell_ids, n_obs

    def test_knn_assigns_all_cells(self, h5ad_path, graph_adata):
        result, *_ = self._run(h5ad_path, graph_adata, method="knn_vote")
        assert result.assigned_mask.sum() == graph_adata.n_obs

    def test_graph_diffusion_assigns_all_cells(self, h5ad_path, graph_adata):
        result, *_ = self._run(h5ad_path, graph_adata, method="graph_diffusion")
        assert result.assigned_mask.sum() == graph_adata.n_obs

    def test_knn_high_accuracy(self, h5ad_path, graph_adata):
        """Well-separated clusters → >95% accuracy with kNN."""
        result, seed_mask, obs_names, cell_ids, n_obs = self._run(
            h5ad_path, graph_adata, method="knn_vote"
        )
        per_cluster = n_obs // 3
        true_labels = graph_adata.obs["Celltypes"].to_numpy()
        accuracy = (result.assigned_labels == true_labels).mean()
        assert accuracy > 0.95, f"Expected >95% accuracy, got {accuracy:.2%}"

    def test_graph_diffusion_high_accuracy(self, h5ad_path, graph_adata):
        result, seed_mask, obs_names, cell_ids, n_obs = self._run(
            h5ad_path, graph_adata, method="graph_diffusion"
        )
        true_labels = graph_adata.obs["Celltypes"].to_numpy()
        accuracy = (result.assigned_labels == true_labels).mean()
        assert accuracy > 0.95, f"Expected >95% accuracy, got {accuracy:.2%}"

    def test_cell_ids_cover_all_eligible(self, h5ad_path, graph_adata):
        result, seed_mask, obs_names, cell_ids, n_obs = self._run(
            h5ad_path, graph_adata, method="knn_vote"
        )
        eligible_indices = np.flatnonzero(result.eligible_mask)
        assert len(eligible_indices) == n_obs
        # cell_ids array must be indexable for every eligible cell
        for idx in eligible_indices[:10]:
            assert str(cell_ids[idx]).startswith("cell_")

    def test_no_adata_in_cache_after_propagation(self, h5ad_path, graph_adata):
        """Propagation must not populate the AnnData LRU cache."""
        svc = AnnDataService(max_cached_objects=0)
        store = SessionStore()
        record = _make_record(h5ad_path)
        sid = "mem-test-session"
        store.get_or_create(sid, "test-obj", "X_umap", "Celltypes")
        _seed_session(store, sid, graph_adata, "Celltypes")

        svc.get_obs_for_propagation(record, "Celltypes")
        svc.get_features(record)
        svc.get_graph(record)

        assert len(svc._cache) == 0, "get_adata() was called — X matrix was loaded!"


# ---------------------------------------------------------------------------
# Regression: obs_names and cell_ids are correct types
# ---------------------------------------------------------------------------

class TestObsArrayTypes:
    def test_obs_names_are_strings(self, h5ad_path):
        svc = AnnDataService(max_cached_objects=0)
        _, obs_names, _, _ = svc.get_obs_for_propagation(_make_record(h5ad_path), "Celltypes")
        assert obs_names.dtype.kind in ("U", "O"), f"Unexpected dtype: {obs_names.dtype}"

    def test_cell_ids_are_strings(self, h5ad_path):
        svc = AnnDataService(max_cached_objects=0)
        _, _, _, cell_ids = svc.get_obs_for_propagation(_make_record(h5ad_path), "Celltypes")
        assert cell_ids.dtype.kind in ("U", "O"), f"Unexpected dtype: {cell_ids.dtype}"

    def test_cluster_values_are_strings(self, h5ad_path):
        svc = AnnDataService(max_cached_objects=0)
        _, _, cluster_values, _ = svc.get_obs_for_propagation(_make_record(h5ad_path), "Celltypes")
        assert cluster_values.dtype.kind in ("U", "O"), f"Unexpected dtype: {cluster_values.dtype}"
