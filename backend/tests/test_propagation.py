"""Tests for propagation algorithms."""
from __future__ import annotations

import numpy as np
import pytest
from app.services.propagation import (
    build_knn_graph,
    run_graph_diffusion,
    run_knn_vote,
)


def make_features(n: int = 100) -> np.ndarray:
    rng = np.random.default_rng(7)
    half = n // 2
    a = rng.standard_normal((half, 2)) + np.array([5, 0])
    b = rng.standard_normal((n - half, 2)) + np.array([-5, 0])
    return np.vstack([a, b]).astype(np.float32)


def make_seed_array(n: int, pos_label: str = "A", neg_label: str = "B", n_seeds: int = 20) -> np.ndarray:
    """n_seeds from each end; empty string = unseeded."""
    arr = np.array([""] * n, dtype=object)
    for i in range(n_seeds):
        arr[i] = pos_label
    for i in range(n - n_seeds, n):
        arr[i] = neg_label
    return arr


class TestBuildKnnGraph:
    def test_shape(self):
        X = make_features(50)
        g = build_knn_graph(X, n_neighbors=10)
        assert g.shape == (50, 50)

    def test_symmetric(self):
        X = make_features(50)
        g = build_knn_graph(X, n_neighbors=10)
        diff = (g - g.T).data
        assert np.allclose(diff, 0, atol=1e-6)

    def test_no_self_edges(self):
        X = make_features(30)
        g = build_knn_graph(X, n_neighbors=5)
        assert g.diagonal().sum() == pytest.approx(0)


class TestKnnVote:
    def _run(self, n: int = 100, annotate_all: bool = True):
        X = make_features(n)
        seeds = make_seed_array(n)
        eligible = np.ones(n, dtype=bool)
        return run_knn_vote(
            features=X,
            seed_label_names=seeds,
            eligible_mask=eligible,
            n_neighbors=15,
            min_score=0.5,
            min_margin=0.0,
            annotate_all=annotate_all,
        )

    def test_assigns_all_when_annotate_all(self):
        n = 100
        result = self._run(n, annotate_all=True)
        assert result.assigned_mask.sum() == n

    def test_label_names(self):
        result = self._run()
        assert set(result.label_names) == {"A", "B"}

    def test_scores_in_range(self):
        result = self._run(60)
        assert (result.scores >= 0).all()
        assert (result.scores <= 1).all()

    def test_reasonable_accuracy(self):
        n = 200
        result = self._run(n, annotate_all=True)
        half = n // 2
        assigned = result.assigned_labels
        first_half_a = (assigned[:half] == "A").mean()
        second_half_b = (assigned[half:] == "B").mean()
        assert first_half_a > 0.8, f"Expected >80% A in first half, got {first_half_a:.2f}"
        assert second_half_b > 0.8, f"Expected >80% B in second half, got {second_half_b:.2f}"


class TestGraphDiffusion:
    def _run(self, n: int = 80, annotate_all: bool = True):
        X = make_features(n)
        seeds = make_seed_array(n)
        eligible = np.ones(n, dtype=bool)
        graph = build_knn_graph(X, n_neighbors=15)
        return run_graph_diffusion(
            graph=graph,
            seed_label_names=seeds,
            eligible_mask=eligible,
            alpha=0.85,
            max_iter=50,
            tol=1e-4,
            min_score=0.5,
            min_margin=0.0,
            annotate_all=annotate_all,
            smoothing=0.0,
        )

    def test_assigns_cells(self):
        result = self._run()
        assert result.assigned_mask.sum() > 0

    def test_label_names_present(self):
        result = self._run()
        assert "A" in result.label_names
        assert "B" in result.label_names

    def test_scores_non_negative(self):
        result = self._run(60)
        assert (result.scores >= 0).all()

    def test_reasonable_accuracy(self):
        n = 160
        result = self._run(n, annotate_all=True)
        half = n // 2
        first_half_a = (result.assigned_labels[:half] == "A").mean()
        assert first_half_a > 0.7
