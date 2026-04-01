from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np


@dataclass
class ObjectRecord:
    object_id: str
    lineage_name: str
    object_path: Path
    lineage_dir: Path
    manifest_path: Path | None = None
    cluster_sizes_path: Path | None = None
    feature_panel_path: Path | None = None
    n_cells: int | None = None
    n_genes: int | None = None
    is_valid: bool = True
    validation_error: str | None = None
    resolution_trials: list[dict[str, Any]] = field(default_factory=list)
    manifest: dict[str, Any] = field(default_factory=dict)


@dataclass
class PolygonSeedBatch:
    polygon_id: str
    label: str
    display_name: str | None
    notes: str | None
    cell_indices: np.ndarray
    vertices: list[list[float]]


@dataclass
class PropagationSnapshot:
    label_names: list[str]
    assigned_labels: np.ndarray
    assigned_scores: np.ndarray
    assigned_margins: np.ndarray
    eligible_mask: np.ndarray
    assigned_mask: np.ndarray
    method: str
    scope: str
    min_score: float
    min_margin: float
    annotate_all: bool
    graph_smoothing: float
    cluster_key: str


@dataclass
class SessionState:
    session_id: str
    object_id: str
    embedding_key: str
    cluster_key: str
    polygon_batches: list[PolygonSeedBatch] = field(default_factory=list)
    seed_labels: dict[int, str] = field(default_factory=dict)
    seed_polygon_ids: dict[int, set[str]] = field(default_factory=dict)
    seed_display_names: dict[str, str] = field(default_factory=dict)
    last_propagation: PropagationSnapshot | None = None

    def register_batch(self, batch: PolygonSeedBatch) -> None:
        self.polygon_batches.append(batch)
        display_name = batch.display_name or batch.label
        self.seed_display_names[batch.label] = display_name
        for index in batch.cell_indices.tolist():
            self.seed_labels[index] = batch.label
            self.seed_polygon_ids.setdefault(index, set()).add(batch.polygon_id)
