from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _path_env(name: str, default: str) -> Path:
    return Path(os.environ.get(name, default)).expanduser()


@dataclass(frozen=True)
class Settings:
    project_root: Path = _path_env("INTERACTIVE_ANNOTATION_PROJECT_ROOT", "/app")
    default_data_root: Path = _path_env("INTERACTIVE_ANNOTATION_DATA_ROOT", "/data")
    default_lineage_root: Path = _path_env(
        "INTERACTIVE_ANNOTATION_LINEAGE_ROOT",
        "/data/lineages_current",
    )
    default_global_object_path: Path = _path_env(
        "INTERACTIVE_ANNOTATION_GLOBAL_OBJECT_PATH",
        "/data/adata_global.h5ad",
    )
    max_cached_objects: int = int(os.environ.get("INTERACTIVE_ANNOTATION_MAX_CACHED_OBJECTS", "2"))
    default_display_points: int = int(os.environ.get("INTERACTIVE_ANNOTATION_DEFAULT_DISPLAY_POINTS", "50000"))
    min_points_per_cluster: int = int(os.environ.get("INTERACTIVE_ANNOTATION_MIN_POINTS_PER_CLUSTER", "250"))
    default_neighbors: int = int(os.environ.get("INTERACTIVE_ANNOTATION_DEFAULT_NEIGHBORS", "15"))
    diffusion_alpha: float = float(os.environ.get("INTERACTIVE_ANNOTATION_DIFFUSION_ALPHA", "0.9"))
    diffusion_max_iter: int = int(os.environ.get("INTERACTIVE_ANNOTATION_DIFFUSION_MAX_ITER", "50"))
    diffusion_tol: float = float(os.environ.get("INTERACTIVE_ANNOTATION_DIFFUSION_TOL", "1e-5"))
    confidence_threshold: float = float(os.environ.get("INTERACTIVE_ANNOTATION_CONFIDENCE_THRESHOLD", "0.7"))
    margin_threshold: float = float(os.environ.get("INTERACTIVE_ANNOTATION_MARGIN_THRESHOLD", "0.1"))


settings = Settings()
