from __future__ import annotations

import numpy as np


def _proportional_quotas(counts: np.ndarray, total: int) -> np.ndarray:
    if total <= 0 or counts.sum() <= 0:
        return np.zeros_like(counts, dtype=int)

    scaled = counts / counts.sum() * total
    quotas = np.minimum(counts, np.floor(scaled).astype(int))
    remaining = int(total - quotas.sum())

    while remaining > 0:
        eligible = np.flatnonzero(counts > quotas)
        if eligible.size == 0:
            break
        order = eligible[np.argsort(-(scaled[eligible] - quotas[eligible]))]
        take = order[:remaining]
        quotas[take] += 1
        remaining = int(total - quotas.sum())

    return np.minimum(quotas, counts).astype(int)


def stratified_sample_indices(
    labels: np.ndarray,
    max_points: int,
    min_per_cluster: int,
    max_per_cluster: int | None,
    random_seed: int,
) -> np.ndarray:
    n_obs = labels.shape[0]
    if n_obs == 0 or max_points <= 0:
        return np.array([], dtype=int)

    label_values, inverse = np.unique(labels, return_inverse=True)
    counts = np.bincount(inverse)
    capped_counts = (
        np.minimum(counts, int(max_per_cluster))
        if max_per_cluster is not None and int(max_per_cluster) > 0
        else counts.astype(int, copy=True)
    )

    if capped_counts.sum() <= max_points:
        quotas = capped_counts.astype(int, copy=True)
    else:
        quotas = np.minimum(capped_counts, min_per_cluster).astype(int)
        quota_total = int(quotas.sum())
        if quota_total > max_points:
            quotas = _proportional_quotas(capped_counts, max_points)
            quota_total = int(quotas.sum())
        remaining = max(max_points - quota_total, 0)
        residual = np.maximum(capped_counts - quotas, 0)

        if residual.sum() > 0 and remaining > 0:
            scaled = residual / residual.sum() * remaining
            extra = np.floor(scaled).astype(int)
            leftovers = remaining - int(extra.sum())
            if leftovers > 0:
                order = np.argsort(-(scaled - extra))
                extra[order[:leftovers]] += 1
            quotas = np.minimum(capped_counts, quotas + extra)

    if n_obs <= max_points and np.array_equal(quotas, counts):
        return np.arange(n_obs, dtype=int)

    rng = np.random.default_rng(random_seed)

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


def priority_stratified_sample_indices(
    labels: np.ndarray,
    priority_mask: np.ndarray,
    max_points: int,
    min_per_cluster: int,
    max_per_cluster: int | None,
    random_seed: int,
) -> np.ndarray:
    priority_mask = np.asarray(priority_mask, dtype=bool)
    if labels.shape[0] != priority_mask.shape[0]:
        raise ValueError("labels and priority_mask must have the same length")

    priority_indices = np.flatnonzero(priority_mask)
    if priority_indices.size == labels.shape[0]:
        return stratified_sample_indices(
            labels=labels[priority_indices],
            max_points=max_points,
            min_per_cluster=min_per_cluster,
            max_per_cluster=max_per_cluster,
            random_seed=random_seed,
        )

    background_indices = np.flatnonzero(~priority_mask)
    if priority_indices.size >= max_points and background_indices.size > 0:
        background_quota = min(background_indices.size, max(1, max_points // 4))
        priority_quota = max_points - int(background_quota)
        chosen_priority = stratified_sample_indices(
            labels=labels[priority_indices],
            max_points=priority_quota,
            min_per_cluster=min_per_cluster,
            max_per_cluster=max_per_cluster,
            random_seed=random_seed,
        )
        chosen_background = stratified_sample_indices(
            labels=labels[background_indices],
            max_points=int(background_quota),
            min_per_cluster=min_per_cluster,
            max_per_cluster=max_per_cluster,
            random_seed=random_seed,
        )
        return np.sort(
            np.concatenate([
                priority_indices[chosen_priority],
                background_indices[chosen_background],
            ])
        )

    if priority_indices.size >= max_points:
        chosen = stratified_sample_indices(
            labels=labels[priority_indices],
            max_points=max_points,
            min_per_cluster=min_per_cluster,
            max_per_cluster=max_per_cluster,
            random_seed=random_seed,
        )
        return np.sort(priority_indices[chosen])

    remaining = max(max_points - int(priority_indices.size), 0)
    if remaining == 0:
        return np.sort(priority_indices)

    background_sample = stratified_sample_indices(
        labels=labels[background_indices],
        max_points=remaining,
        min_per_cluster=min_per_cluster,
        max_per_cluster=max_per_cluster,
        random_seed=random_seed,
    )
    chosen_background = background_indices[background_sample]
    return np.sort(np.concatenate([priority_indices, chosen_background]))
