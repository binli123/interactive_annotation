from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import sparse
from sklearn.neighbors import NearestNeighbors


@dataclass
class PropagationResult:
    label_names: list[str]
    assigned_labels: np.ndarray
    scores: np.ndarray
    margins: np.ndarray
    assigned_mask: np.ndarray
    eligible_mask: np.ndarray


def row_normalize(matrix: sparse.spmatrix) -> sparse.csr_matrix:
    csr = matrix.tocsr(copy=True)
    row_sums = np.asarray(csr.sum(axis=1)).ravel()
    row_sums[row_sums == 0] = 1.0
    inv = 1.0 / row_sums
    return sparse.diags(inv) @ csr


def build_knn_graph(features: np.ndarray, n_neighbors: int) -> sparse.csr_matrix:
    n_neighbors = min(max(1, n_neighbors), features.shape[0])
    nn = NearestNeighbors(n_neighbors=n_neighbors, metric="euclidean")
    nn.fit(features)
    distances, indices = nn.kneighbors(features)
    rows = np.repeat(np.arange(features.shape[0]), n_neighbors)
    cols = indices.reshape(-1)
    weights = 1.0 / (1.0 + distances.reshape(-1))
    graph = sparse.csr_matrix((weights, (rows, cols)), shape=(features.shape[0], features.shape[0]))
    graph = graph.maximum(graph.T)
    graph.setdiag(0)
    graph.eliminate_zeros()
    return graph


def neighborhood_mask(graph: sparse.spmatrix, seed_mask: np.ndarray, hops: int = 2) -> np.ndarray:
    adjacency = graph.tocsr()
    frontier = seed_mask.astype(bool).copy()
    reached = frontier.copy()
    for _ in range(max(hops, 1)):
        frontier = adjacency[frontier].sum(axis=0).A1 > 0
        frontier &= ~reached
        reached |= frontier
        if not frontier.any():
            break
    return reached


def diffuse_scores(
    graph: sparse.spmatrix,
    seed_label_names: np.ndarray,
    alpha: float,
    max_iter: int,
    tol: float,
) -> tuple[list[str], np.ndarray]:
    labels = sorted({label for label in seed_label_names.tolist() if label})
    if not labels:
        raise ValueError("No seed labels were provided.")

    normalized_graph = row_normalize(graph)
    n_obs = graph.shape[0]
    seed_matrix = np.zeros((n_obs, len(labels)), dtype=float)
    label_to_col = {label: idx for idx, label in enumerate(labels)}

    seeded_rows = np.flatnonzero(seed_label_names != "")
    for row in seeded_rows:
        seed_matrix[row, label_to_col[seed_label_names[row]]] = 1.0

    scores = seed_matrix.copy()
    seed_mask = seeded_rows

    for _ in range(max_iter):
        updated = alpha * normalized_graph.dot(scores) + (1.0 - alpha) * seed_matrix
        if seed_mask.size:
            updated[seed_mask] = seed_matrix[seed_mask]
        row_sums = updated.sum(axis=1, keepdims=True)
        non_zero = row_sums.squeeze() > 0
        updated[non_zero] = updated[non_zero] / row_sums[non_zero]
        delta = float(np.max(np.abs(updated - scores)))
        scores = updated
        if delta < tol:
            break

    return labels, scores


def apply_graph_smoothing(
    graph: sparse.spmatrix,
    scores: np.ndarray,
    seed_label_names: np.ndarray,
    smoothing: float,
    passes: int = 2,
) -> np.ndarray:
    smoothing = float(np.clip(smoothing, 0.0, 1.0))
    if smoothing <= 0.0:
        return scores

    normalized_graph = row_normalize(graph)
    smoothed = scores.copy()
    seeded_rows = np.flatnonzero(seed_label_names != "")
    for _ in range(max(1, passes)):
        updated = (1.0 - smoothing) * smoothed + smoothing * normalized_graph.dot(smoothed)
        if seeded_rows.size:
            updated[seeded_rows] = scores[seeded_rows]
        row_sums = updated.sum(axis=1, keepdims=True)
        non_zero = row_sums.squeeze() > 0
        updated[non_zero] = updated[non_zero] / row_sums[non_zero]
        smoothed = updated
    return smoothed


def assign_from_scores(
    label_names: list[str],
    scores: np.ndarray,
    eligible_mask: np.ndarray,
    min_score: float,
    min_margin: float,
    annotate_all: bool = False,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    n_obs = scores.shape[0]
    top_idx = np.argmax(scores, axis=1)
    top_score = scores[np.arange(n_obs), top_idx]
    if scores.shape[1] > 1:
        sorted_scores = np.sort(scores, axis=1)
        second_best = sorted_scores[:, -2]
    else:
        second_best = np.zeros(n_obs, dtype=float)
    margins = top_score - second_best

    if annotate_all:
        assigned_mask = eligible_mask.copy()
    else:
        assigned_mask = eligible_mask & (top_score >= min_score) & (margins >= min_margin)
    assigned_labels = np.array(["Unassigned"] * n_obs, dtype=object)
    assigned_labels[assigned_mask] = np.asarray(label_names, dtype=object)[top_idx[assigned_mask]]
    return assigned_labels, top_score, margins, assigned_mask


def run_graph_diffusion(
    graph: sparse.spmatrix,
    seed_label_names: np.ndarray,
    eligible_mask: np.ndarray,
    alpha: float,
    max_iter: int,
    tol: float,
    min_score: float,
    min_margin: float,
    annotate_all: bool,
    smoothing: float,
) -> PropagationResult:
    labels, scores = diffuse_scores(graph=graph, seed_label_names=seed_label_names, alpha=alpha, max_iter=max_iter, tol=tol)
    scores = apply_graph_smoothing(
        graph=graph,
        scores=scores,
        seed_label_names=seed_label_names,
        smoothing=smoothing,
    )
    assigned_labels, top_score, margins, assigned_mask = assign_from_scores(
        label_names=labels,
        scores=scores,
        eligible_mask=eligible_mask,
        min_score=min_score,
        min_margin=min_margin,
        annotate_all=annotate_all,
    )
    return PropagationResult(
        label_names=labels,
        assigned_labels=assigned_labels,
        scores=top_score,
        margins=margins,
        assigned_mask=assigned_mask,
        eligible_mask=eligible_mask,
    )


def run_knn_vote(
    features: np.ndarray,
    seed_label_names: np.ndarray,
    eligible_mask: np.ndarray,
    n_neighbors: int,
    min_score: float,
    min_margin: float,
    annotate_all: bool,
) -> PropagationResult:
    labels = sorted({label for label in seed_label_names.tolist() if label})
    if not labels:
        raise ValueError("No seed labels were provided.")

    seeded_rows = np.flatnonzero(seed_label_names != "")
    if seeded_rows.size == 0:
        raise ValueError("No seed cells available for kNN propagation.")

    ref_features = features[seeded_rows]
    ref_labels = seed_label_names[seeded_rows]
    n_neighbors = max(1, min(n_neighbors, ref_features.shape[0]))
    nn = NearestNeighbors(n_neighbors=n_neighbors, metric="euclidean")
    nn.fit(ref_features)
    _, indices = nn.kneighbors(features)

    label_to_col = {label: idx for idx, label in enumerate(labels)}
    votes = np.zeros((features.shape[0], len(labels)), dtype=float)
    for row in range(features.shape[0]):
        for neighbor in indices[row]:
            votes[row, label_to_col[ref_labels[neighbor]]] += 1.0
    votes /= votes.sum(axis=1, keepdims=True)

    assigned_labels, top_score, margins, assigned_mask = assign_from_scores(
        label_names=labels,
        scores=votes,
        eligible_mask=eligible_mask,
        min_score=min_score,
        min_margin=min_margin,
        annotate_all=annotate_all,
    )

    return PropagationResult(
        label_names=labels,
        assigned_labels=assigned_labels,
        scores=top_score,
        margins=margins,
        assigned_mask=assigned_mask,
        eligible_mask=eligible_mask,
    )
