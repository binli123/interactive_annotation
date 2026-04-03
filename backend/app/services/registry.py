from __future__ import annotations

import hashlib
import json
from pathlib import Path

import anndata as ad
import h5py
import pandas as pd

from app.core.config import settings
from app.models.state import ObjectRecord


def _normalize_lineage_name(name: str) -> str:
    return name.replace("_", " ").strip().lower()


def _inspect_h5ad(object_path: Path) -> tuple[int | None, int | None, bool, str | None]:
    try:
        adata = ad.read_h5ad(object_path, backed="r")
        n_obs, n_vars = int(adata.n_obs), int(adata.n_vars)
        embedding_keys = list(adata.obsm.keys())
        adata.file.close()
        if not embedding_keys:
            return n_obs, n_vars, False, "No embeddings available for viewing."
        return n_obs, n_vars, True, None
    except Exception:
        try:
            with h5py.File(object_path, "r") as handle:
                n_obs = None
                n_vars = None
                if "obs" in handle and "_index" in handle["obs"]:
                    n_obs = int(handle["obs"]["_index"].shape[0])
                if "var" in handle and "_index" in handle["var"]:
                    n_vars = int(handle["var"]["_index"].shape[0])
                elif "X" in handle:
                    x = handle["X"]
                    if isinstance(x, h5py.Dataset) and len(x.shape) == 2:
                        n_vars = int(x.shape[1])
                    elif isinstance(x, h5py.Group) and "shape" in x.attrs:
                        shape = x.attrs["shape"]
                        n_vars = int(shape[1])
                missing = []
                for key in ("var", "obsm"):
                    if key not in handle:
                        missing.append(key)
                error = None
                is_valid = len(missing) == 0
                if not is_valid:
                    error = f"Missing required groups for viewing: {', '.join(missing)}"
                elif "obsm" in handle and len(handle["obsm"].keys()) == 0:
                    is_valid = False
                    error = "No embeddings available for viewing."
                return n_obs, n_vars, is_valid, error
        except Exception as inner_exc:
            return None, None, False, f"Unreadable h5ad: {inner_exc}"


class ObjectRegistry:
    def __init__(self) -> None:
        self._records: dict[str, ObjectRecord] = {}
        self._scan_root: Path | None = None

    def build_record(
        self,
        object_path: Path,
        lineage_name: str | None = None,
        lineage_dir: Path | None = None,
        manifest: dict | None = None,
        resolution_trials: list[dict[str, object]] | None = None,
    ) -> ObjectRecord:
        object_path = object_path.expanduser().resolve()
        if not object_path.exists():
            raise FileNotFoundError(f"Object file does not exist: {object_path}")
        lineage_dir = (lineage_dir or object_path.parent).expanduser().resolve()
        manifest = dict(manifest or {})
        inferred_n_cells, inferred_n_genes, is_valid, validation_error = _inspect_h5ad(object_path)
        effective_lineage_name = str(lineage_name or manifest.get("lineage") or object_path.stem)
        object_id = hashlib.sha1(str(object_path).encode("utf-8")).hexdigest()[:12]
        manifest_path = lineage_dir / "recluster_manifest.json"
        return ObjectRecord(
            object_id=object_id,
            lineage_name=effective_lineage_name,
            object_path=object_path,
            lineage_dir=lineage_dir,
            manifest_path=manifest_path if manifest_path.exists() else None,
            cluster_sizes_path=lineage_dir / "cluster_sizes_by_resolution.csv",
            feature_panel_path=lineage_dir / "feature_panel_summary.csv",
            n_cells=manifest.get("n_cells", inferred_n_cells),
            n_genes=manifest.get("n_genes", inferred_n_genes),
            is_valid=is_valid,
            validation_error=validation_error,
            resolution_trials=list(resolution_trials or []),
            manifest=manifest,
        )

    def scan(self, folder: Path | None = None) -> list[ObjectRecord]:
        candidate = folder or settings.default_lineage_root
        root = candidate.expanduser().resolve()
        lineage_root = root / "lineages" if root.name != "lineages" and (root / "lineages").exists() else root
        if not lineage_root.exists():
            raise FileNotFoundError(f"Lineage folder does not exist: {lineage_root}")

        summary_path = lineage_root.parent / "summary_resolution_trials.csv"
        summary_df = pd.read_csv(summary_path) if summary_path.exists() else pd.DataFrame()
        summary_map: dict[str, list[dict[str, object]]] = {}
        if not summary_df.empty:
            for _, row in summary_df.iterrows():
                summary_map.setdefault(_normalize_lineage_name(str(row["lineage"])), []).append(row.to_dict())

        records: dict[str, ObjectRecord] = {}

        def register_object(lineage_dir: Path, object_path: Path, lineage_name_override: str | None = None) -> None:
            manifest_path = lineage_dir / "recluster_manifest.json"
            manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
            lineage_name = str(
                lineage_name_override
                or manifest.get("lineage")
                or lineage_dir.name
            )
            record = self.build_record(
                object_path=object_path,
                lineage_name=lineage_name,
                lineage_dir=lineage_dir,
                manifest=manifest,
                resolution_trials=summary_map.get(_normalize_lineage_name(lineage_name), []),
            )
            records[record.object_id] = record

        lineage_dirs = [path for path in lineage_root.iterdir() if path.is_dir()]
        if lineage_dirs:
            for lineage_dir in sorted(lineage_dirs):
                for object_path in sorted(lineage_dir.glob("*.h5ad")):
                    register_object(lineage_dir, object_path)
        else:
            for object_path in sorted(lineage_root.glob("*.h5ad")):
                register_object(lineage_root, object_path, lineage_name_override=object_path.stem)

        self._records = records
        self._scan_root = lineage_root
        return list(records.values())

    def list_records(self) -> list[ObjectRecord]:
        if not self._records:
            self.scan(settings.default_lineage_root)
        return list(self._records.values())

    def get(self, object_id: str) -> ObjectRecord:
        if object_id not in self._records:
            self.list_records()
        try:
            return self._records[object_id]
        except KeyError as exc:
            raise KeyError(f"Unknown object_id: {object_id}") from exc

    @property
    def scan_root(self) -> Path | None:
        return self._scan_root


registry = ObjectRegistry()
