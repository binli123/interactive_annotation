"""Shared fixtures for the test suite."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pytest
import anndata as ad
import pandas as pd
import scipy.sparse as sparse

from app.services.propagation import build_knn_graph


def make_adata(
    n_cells: int = 200,
    n_genes: int = 50,
    n_clusters: int = 4,
    seed: int = 42,
    with_spatial: bool = False,
) -> ad.AnnData:
    rng = np.random.default_rng(seed)
    X = rng.poisson(lam=2, size=(n_cells, n_genes)).astype(np.float32)
    cluster_ids = (np.arange(n_cells) % n_clusters).astype(str)
    obs = pd.DataFrame(
        {
            "leiden": cluster_ids,
            "n_genes_by_counts": rng.integers(200, 2000, n_cells),
            "total_counts": rng.integers(500, 5000, n_cells).astype(float),
            "pct_counts_mt": rng.uniform(0, 20, n_cells),
            "batch": rng.choice(["A", "B"], n_cells),
        },
        index=[f"cell_{i}" for i in range(n_cells)],
    )
    var = pd.DataFrame(index=[f"gene_{i}" for i in range(n_genes)])
    adata = ad.AnnData(X=X, obs=obs, var=var)
    rng2 = np.random.default_rng(seed + 1)
    adata.obsm["X_umap"] = rng2.standard_normal((n_cells, 2)).astype(np.float32)
    if with_spatial:
        adata.obsm["spatial"] = rng2.uniform(0, 1000, (n_cells, 2)).astype(np.float32)
    return adata


def make_adata_with_graph(
    n_cells: int = 300,
    n_genes: int = 30,
    n_clusters: int = 3,
    seed: int = 42,
) -> ad.AnnData:
    """Full fixture: sparse X, clustered PCA, connectivity graph, cell_id column.

    Clusters are well-separated in PCA space so propagation produces
    high-accuracy labels even with few seeds.
    """
    rng = np.random.default_rng(seed)
    per_cluster = n_cells // n_clusters
    # Align n_cells to a multiple of n_clusters so array lengths are consistent
    n_cells = per_cluster * n_clusters

    # Sparse X matrix
    X = sparse.random(n_cells, n_genes, density=0.15, random_state=seed, format="csr", dtype=np.float32)

    # Well-separated cluster centres in 20-D PCA space
    cluster_labels = np.repeat(np.arange(n_clusters), per_cluster)
    centers = np.eye(n_clusters, 20) * 8.0
    X_pca = np.vstack([
        rng.standard_normal((per_cluster, 20)) + centers[c]
        for c in range(n_clusters)
    ]).astype(np.float32)

    celltype_names = ["TypeA", "TypeB", "TypeC", "TypeD", "TypeE"][:n_clusters]
    obs = pd.DataFrame(
        {
            "Celltypes": np.array(celltype_names)[cluster_labels],
            "leiden": cluster_labels.astype(str),
            "cell_id": [f"cell_{i}" for i in range(n_cells)],
        },
        index=[f"obs_{i}" for i in range(n_cells)],
    )
    var = pd.DataFrame(index=[f"gene_{i}" for i in range(n_genes)])

    adata = ad.AnnData(X=X, obs=obs, var=var)
    adata.obsm["X_pca_lineage"] = X_pca
    adata.obsm["X_umap"] = rng.standard_normal((n_cells, 2)).astype(np.float32)

    graph = build_knn_graph(X_pca, n_neighbors=10)
    adata.obsp["lineage_connectivities"] = graph

    return adata


@pytest.fixture
def tiny_adata() -> ad.AnnData:
    return make_adata()


@pytest.fixture
def spatial_adata() -> ad.AnnData:
    return make_adata(with_spatial=True)


@pytest.fixture
def graph_adata() -> ad.AnnData:
    """AnnData with PCA, connectivity graph, and cell_id — ready for propagation."""
    return make_adata_with_graph()


@pytest.fixture
def h5ad_path(tmp_path: Path, graph_adata: ad.AnnData) -> Path:
    """Write graph_adata to a temp h5ad file and return the path."""
    path = tmp_path / "test_object.h5ad"
    graph_adata.write_h5ad(path)
    return path
