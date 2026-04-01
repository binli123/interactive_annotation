from __future__ import annotations

import numpy as np


def stratified_sample_indices(
    labels: np.ndarray,
    max_points: int,
    min_per_cluster: int,
    random_seed: int,
) -> np.ndarray:
    n_obs = labels.shape[0]
    if n_obs <= max_points:
        return np.arange(n_obs, dtype=int)

    rng = np.random.default_rng(random_seed)
    label_values, inverse = np.unique(labels, return_inverse=True)
    counts = np.bincount(inverse)
    quotas = np.minimum(counts, min_per_cluster).astype(int)
    quota_total = int(quotas.sum())
    remaining = max(max_points - quota_total, 0)
    residual = np.maximum(counts - quotas, 0)

    if residual.sum() > 0 and remaining > 0:
        scaled = residual / residual.sum() * remaining
        extra = np.floor(scaled).astype(int)
        leftovers = remaining - int(extra.sum())
        if leftovers > 0:
            order = np.argsort(-(scaled - extra))
            extra[order[:leftovers]] += 1
        quotas = np.minimum(counts, quotas + extra)

    chosen: list[np.ndarray] = []
    for label_index, _ in enumerate(label_values):
        member_indices = np.flatnonzero(inverse == label_index)
        take = min(member_indices.size, int(quotas[label_index]))
        if take == member_indices.size:
            chosen.append(member_indices)
        elif take > 0:
            chosen.append(np.sort(rng.choice(member_indices, size=take, replace=False)))

    if not chosen:
        return np.sort(rng.choice(np.arange(n_obs, dtype=int), size=max_points, replace=False))

    return np.sort(np.concatenate(chosen))
