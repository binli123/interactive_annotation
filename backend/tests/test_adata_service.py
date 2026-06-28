"""Tests for AnnDataService feature methods (DE, export, diff, obs columns)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest
import anndata as ad

from app.services.adata_service import AnnDataService
from app.models.state import ObjectRecord


def _make_record(tmp_path: Path) -> ObjectRecord:
    """Minimal ObjectRecord for testing; object_path is never opened (get_adata mocked)."""
    return ObjectRecord(
        object_id="test_obj",
        lineage_name="test_lineage",
        object_path=tmp_path / "test.h5ad",
        lineage_dir=tmp_path,
    )


def _make_adata(n_cells: int = 100, n_genes: int = 30) -> ad.AnnData:
    rng = np.random.default_rng(42)
    X = rng.poisson(lam=2, size=(n_cells, n_genes)).astype(np.float32)
    cluster_ids = (np.arange(n_cells) % 4).astype(str)
    obs = pd.DataFrame(
        {
            "leiden": cluster_ids,
            "n_genes_by_counts": rng.integers(200, 2000, n_cells),
            "total_counts": rng.uniform(500, 5000, n_cells),
            "pct_counts_mt": rng.uniform(0, 20, n_cells),
            "batch": rng.choice(["A", "B"], n_cells),
        },
        index=[f"cell_{i}" for i in range(n_cells)],
    )
    var = pd.DataFrame(index=[f"gene_{i}" for i in range(n_genes)])
    adata = ad.AnnData(X=X, obs=obs, var=var)
    adata.obsm["X_umap"] = rng.standard_normal((n_cells, 2)).astype(np.float32)
    return adata


@pytest.fixture
def service() -> AnnDataService:
    return AnnDataService(max_cached_objects=4)


@pytest.fixture
def record(tmp_path: Path) -> ObjectRecord:
    return _make_record(tmp_path)


@pytest.fixture
def adata() -> ad.AnnData:
    return _make_adata()


class TestGetObsColumns:
    def test_returns_all_columns(self, service, record, adata):
        with patch.object(service, "get_adata", return_value=adata):
            result = service.get_obs_columns(record)
        assert result["object_id"] == "test_obj"
        col_names = {c["name"] for c in result["columns"]}
        assert "leiden" in col_names
        assert "n_genes_by_counts" in col_names

    def test_qc_flag_set(self, service, record, adata):
        with patch.object(service, "get_adata", return_value=adata):
            result = service.get_obs_columns(record)
        qc_cols = {c["name"] for c in result["columns"] if c["is_qc"]}
        assert "n_genes_by_counts" in qc_cols
        assert "total_counts" in qc_cols
        assert "pct_counts_mt" in qc_cols

    def test_numeric_dtype(self, service, record, adata):
        with patch.object(service, "get_adata", return_value=adata):
            result = service.get_obs_columns(record)
        col_map = {c["name"]: c for c in result["columns"]}
        assert col_map["total_counts"]["is_numeric"] is True
        assert col_map["leiden"]["is_numeric"] is False


class TestDifferentialExpression:
    def test_basic_de_wilcoxon(self, service, record, adata):
        with patch.object(service, "get_adata", return_value=adata):
            result = service.run_de_analysis(
                record,
                cluster_key="leiden",
                target_clusters=["0"],
                reference_clusters=["1"],
                top_n=10,
                method="wilcoxon",
            )
        assert result["object_id"] == "test_obj"
        assert len(result["genes"]) <= 10
        assert result["n_target_cells"] > 0
        assert result["n_reference_cells"] > 0

    def test_basic_de_ttest(self, service, record, adata):
        with patch.object(service, "get_adata", return_value=adata):
            result = service.run_de_analysis(
                record,
                cluster_key="leiden",
                target_clusters=["2"],
                reference_clusters=[],  # all others
                top_n=20,
                method="t-test",
            )
        assert result["method"] == "t-test"
        assert len(result["genes"]) > 0

    def test_genes_have_required_fields(self, service, record, adata):
        with patch.object(service, "get_adata", return_value=adata):
            result = service.run_de_analysis(
                record,
                cluster_key="leiden",
                target_clusters=["0"],
                reference_clusters=["1", "2"],
                top_n=5,
            )
        for gene in result["genes"]:
            assert "gene_name" in gene
            assert "log_fold_change" in gene
            assert "p_val_adj" in gene
            assert "p_val" in gene
            assert 0 <= gene["p_val_adj"] <= 1.01

    def test_invalid_cluster_key_raises(self, service, record, adata):
        with patch.object(service, "get_adata", return_value=adata):
            with pytest.raises(ValueError, match="not found"):
                service.run_de_analysis(
                    record,
                    cluster_key="nonexistent",
                    target_clusters=["0"],
                    reference_clusters=["1"],
                )

    def test_empty_target_raises(self, service, record, adata):
        with patch.object(service, "get_adata", return_value=adata):
            with pytest.raises(ValueError, match="No cells"):
                service.run_de_analysis(
                    record,
                    cluster_key="leiden",
                    target_clusters=["999"],
                    reference_clusters=["0"],
                )


class TestExportAnnotations:
    def _adata_with_annotations(self) -> ad.AnnData:
        adata = _make_adata(50, 20)
        adata.obs["reannot_label"] = (np.arange(50) % 3).astype(str)
        adata.obs["reannot_display_label"] = adata.obs["reannot_label"]
        adata.obs["reannot_confidence"] = np.random.uniform(0.5, 1.0, 50)
        adata.obs["reannot_margin"] = np.random.uniform(0.1, 0.5, 50)
        return adata

    def test_export_csv(self, service, record):
        adata = self._adata_with_annotations()
        with patch.object(service, "get_adata", return_value=adata):
            with patch.object(service, "_get_cell_ids", return_value=list(adata.obs_names)):
                content, mime = service.export_annotations(record, session_state=None, fmt="csv")
        assert mime == "text/csv"
        assert "cell_barcode" in content
        assert "annotation_label" in content

    def test_export_tsv(self, service, record):
        adata = self._adata_with_annotations()
        with patch.object(service, "get_adata", return_value=adata):
            with patch.object(service, "_get_cell_ids", return_value=list(adata.obs_names)):
                content, mime = service.export_annotations(record, session_state=None, fmt="tsv")
        assert mime == "text/tab-separated-values"
        lines = content.split("\n")
        cols = lines[0].split("\t")
        assert "cell_barcode" in cols

    def test_export_json(self, service, record):
        import json
        adata = self._adata_with_annotations()
        with patch.object(service, "get_adata", return_value=adata):
            with patch.object(service, "_get_cell_ids", return_value=list(adata.obs_names)):
                content, mime = service.export_annotations(record, session_state=None, fmt="json")
        assert mime == "application/json"
        rows = json.loads(content)
        assert isinstance(rows, list)
        assert len(rows) == 50

    def test_no_annotation_raises(self, service, record, adata):
        with patch.object(service, "get_adata", return_value=adata):
            with patch.object(service, "_get_cell_ids", return_value=list(adata.obs_names)):
                with pytest.raises(ValueError, match="No annotation"):
                    service.export_annotations(record, session_state=None, fmt="csv")


class TestCompareClusterColumns:
    def test_identical_columns(self, service, record, adata):
        with patch.object(service, "get_adata", return_value=adata):
            result = service.compare_cluster_columns(record, "leiden", "leiden")
        assert result["changed_cells"] == 0
        assert result["unchanged_cells"] == adata.n_obs

    def test_different_columns(self, service, record):
        adata = _make_adata(60, 10)
        adata.obs["other_cluster"] = (np.arange(60) % 3).astype(str)
        with patch.object(service, "get_adata", return_value=adata):
            result = service.compare_cluster_columns(record, "leiden", "other_cluster")
        assert result["total_cells"] == 60
        assert result["changed_cells"] + result["unchanged_cells"] == 60
        assert isinstance(result["transitions"], list)

    def test_missing_column_raises(self, service, record, adata):
        with patch.object(service, "get_adata", return_value=adata):
            with pytest.raises(ValueError, match="not found"):
                service.compare_cluster_columns(record, "leiden", "nonexistent_col")

    def test_transitions_include_all_pairs(self, service, record, adata):
        adata.obs["alt"] = adata.obs["leiden"].shift(1).fillna("3")
        with patch.object(service, "get_adata", return_value=adata):
            result = service.compare_cluster_columns(record, "leiden", "alt")
        total_from_transitions = sum(t["count"] for t in result["transitions"])
        assert total_from_transitions == result["total_cells"]


class TestSpatialDetection:
    def test_has_spatial_true(self, service):
        adata = _make_adata(50, 10)
        adata.obsm["spatial"] = np.random.uniform(0, 100, (50, 2)).astype(np.float32)
        assert service._has_spatial(adata) is True

    def test_has_spatial_false(self, service):
        adata = _make_adata(50, 10)
        assert service._has_spatial(adata) is False


class TestGetObsValues:
    def test_returns_values_for_indices(self, service, record, adata):
        indices = [0, 5, 10]
        with patch.object(service, "get_adata", return_value=adata):
            result = service.get_obs_values(record, "total_counts", indices)
        assert result["column"] == "total_counts"
        assert result["is_numeric"] is True
        assert len(result["values"]) == 3
        returned_indices = [v["index"] for v in result["values"]]
        assert returned_indices == indices

    def test_categorical_values(self, service, record, adata):
        with patch.object(service, "get_adata", return_value=adata):
            result = service.get_obs_values(record, "leiden", [0, 1, 2])
        assert result["is_numeric"] is False
        assert result["dtype"] == "categorical"
        for v in result["values"]:
            assert isinstance(v["value"], str)

    def test_missing_column_raises(self, service, record, adata):
        with patch.object(service, "get_adata", return_value=adata):
            with pytest.raises(ValueError, match="not found"):
                service.get_obs_values(record, "nonexistent_col", [0])

    def test_empty_indices(self, service, record, adata):
        with patch.object(service, "get_adata", return_value=adata):
            result = service.get_obs_values(record, "leiden", [])
        assert result["values"] == []


class TestAnnotationCoverage:
    def test_no_annotation_column(self, service, record, adata):
        with patch.object(service, "get_adata", return_value=adata):
            result = service.get_annotation_coverage(record)
        assert result["n_cells"] == adata.n_obs
        assert result["n_annotated"] is None
        assert result["annotation_fraction"] is None

    def test_with_annotation_column(self, service, record):
        adata = _make_adata(80, 15)
        # Annotate 40 of 80 cells
        labels = [""] * 80
        for i in range(40):
            labels[i] = "T_cell"
        adata.obs["reannot_label"] = labels
        with patch.object(service, "get_adata", return_value=adata):
            result = service.get_annotation_coverage(record)
        assert result["n_annotated"] == 40
        assert result["annotation_fraction"] == pytest.approx(0.5)
        assert result["annotation_column"] == "reannot_label"

    def test_fully_annotated(self, service, record):
        adata = _make_adata(60, 10)
        adata.obs["reannot_label"] = ["T_cell"] * 60
        with patch.object(service, "get_adata", return_value=adata):
            result = service.get_annotation_coverage(record)
        assert result["annotation_fraction"] == pytest.approx(1.0)

    def test_has_cluster_count(self, service, record, adata):
        with patch.object(service, "get_adata", return_value=adata):
            result = service.get_annotation_coverage(record)
        # n_clusters is from the first detected cluster column (batch or leiden)
        # — just assert it is a positive integer, not None
        assert result["n_clusters"] is not None
        assert result["n_clusters"] > 0
