"""Shared fixtures for the test suite."""
from __future__ import annotations

import sys
from pathlib import Path

# Make `app` importable as a top-level package
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pytest
import anndata as ad
import pandas as pd


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


@pytest.fixture
def tiny_adata() -> ad.AnnData:
    return make_adata()


@pytest.fixture
def spatial_adata() -> ad.AnnData:
    return make_adata(with_spatial=True)
