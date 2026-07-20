from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import json
import numpy as np
import pandas as pd

from app.models.state import PolygonSeedBatch, PropagationSnapshot, SessionState


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, SessionState] = {}

    def get_or_create(
        self,
        session_id: str,
        object_id: str,
        embedding_key: str,
        cluster_key: str,
    ) -> SessionState:
        session = self._sessions.get(session_id)
        if session is None:
            session = SessionState(
                session_id=session_id,
                object_id=object_id,
                embedding_key=embedding_key,
                cluster_key=cluster_key,
            )
            self._sessions[session_id] = session
            return session

        if session.object_id != object_id:
            raise ValueError("Session is already attached to a different object.")
        session.embedding_key = embedding_key
        session.cluster_key = cluster_key
        return session

    def get(self, session_id: str) -> SessionState:
        try:
            return self._sessions[session_id]
        except KeyError as exc:
            raise KeyError(f"Unknown session_id: {session_id}") from exc

    def clear(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def register_batch(self, session_id: str, batch: PolygonSeedBatch) -> SessionState:
        session = self.get(session_id)
        session.register_batch(batch)
        return session

    def attach_propagation(self, session_id: str, snapshot: PropagationSnapshot) -> SessionState:
        session = self.get(session_id)
        session.last_propagation = snapshot
        return session

    def summarize(self, session_id: str) -> dict[str, Any]:
        session = self.get(session_id)
        label_counts = Counter(session.seed_labels.values())
        last = None
        if session.last_propagation is not None:
            last = {
                "method": session.last_propagation.method,
                "scope": session.last_propagation.scope,
                "annotate_all": session.last_propagation.annotate_all,
                "graph_smoothing": session.last_propagation.graph_smoothing,
                "cluster_key": session.last_propagation.cluster_key,
                "n_eligible_cells": int(session.last_propagation.eligible_mask.sum()),
                "n_assigned_cells": int(session.last_propagation.assigned_mask.sum()),
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            }
        return {
            "session_id": session.session_id,
            "object_id": session.object_id,
            "embedding_key": session.embedding_key,
            "cluster_key": session.cluster_key,
            "n_seed_cells": len(session.seed_labels),
            "n_polygons": len(session.polygon_batches),
            "labels": dict(sorted(label_counts.items())),
            "last_propagation": last,
        }

    def session_sidecar(self, session_id: str) -> dict[str, Any]:
        session = self.get(session_id)
        return {
            "session_id": session.session_id,
            "object_id": session.object_id,
            "embedding_key": session.embedding_key,
            "cluster_key": session.cluster_key,
            "seed_labels": {str(index): label for index, label in sorted(session.seed_labels.items())},
            "seed_polygon_ids": {
                str(index): sorted(polygon_ids)
                for index, polygon_ids in sorted(session.seed_polygon_ids.items())
            },
            "labels": session.seed_display_names,
            "polygons": [
                {
                    "polygon_id": batch.polygon_id,
                    "label": batch.label,
                    "display_name": batch.display_name,
                    "notes": batch.notes,
                    "n_cells": int(batch.cell_indices.size),
                    "vertices": batch.vertices,
                }
                for batch in session.polygon_batches
            ],
            "last_propagation": None
            if session.last_propagation is None
            else {
                "method": session.last_propagation.method,
                "scope": session.last_propagation.scope,
                "min_score": session.last_propagation.min_score,
                "min_margin": session.last_propagation.min_margin,
                "annotate_all": session.last_propagation.annotate_all,
                "graph_smoothing": session.last_propagation.graph_smoothing,
                "cluster_key": session.last_propagation.cluster_key,
            },
        }

    def save_sidecars(
        self,
        session_id: str,
        base_path: Path,
        cluster_summary: list[dict[str, Any]],
    ) -> tuple[Path, Path, Path]:
        session = self.get(session_id)
        session_json_path = base_path.with_suffix(".session.json")
        polygons_geojson_path = base_path.with_suffix(".polygons.geojson")
        summary_csv_path = base_path.with_suffix(".summary.csv")

        session_json_path.write_text(json.dumps(self.session_sidecar(session_id), indent=2))

        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        "polygon_id": batch.polygon_id,
                        "label": batch.label,
                        "display_name": batch.display_name,
                        "notes": batch.notes,
                    },
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[list(vertex) for vertex in batch.vertices]],
                    },
                }
                for batch in session.polygon_batches
            ],
        }
        polygons_geojson_path.write_text(json.dumps(geojson, indent=2))
        pd.DataFrame(cluster_summary).to_csv(summary_csv_path, index=False)
        return session_json_path, polygons_geojson_path, summary_csv_path

    # F-03 — Persistent session recovery

    @staticmethod
    def _live_session_path(lineage_dir: Path, object_id: str) -> Path:
        return lineage_dir / f".live_session_{object_id}.json"

    def _live_snapshot(self, session_id: str) -> dict[str, Any]:
        """Like `session_sidecar`, but includes the full computed propagation
        result (not just its parameters) so a backend restart between
        "Propagate" finishing and the user clicking "Save now" doesn't lose
        the computed assignment — only the .h5ad write itself still requires
        an explicit Save."""
        session = self.get(session_id)
        sidecar = self.session_sidecar(session_id)
        if session.last_propagation is not None:
            snapshot = session.last_propagation
            sidecar["last_propagation"] = {
                **sidecar["last_propagation"],
                "label_names": snapshot.label_names,
                "assigned_labels": snapshot.assigned_labels.tolist(),
                "assigned_scores": snapshot.assigned_scores.tolist(),
                "assigned_margins": snapshot.assigned_margins.tolist(),
                "eligible_mask": snapshot.eligible_mask.tolist(),
                "assigned_mask": snapshot.assigned_mask.tolist(),
            }
        return sidecar

    def persist(self, session_id: str, lineage_dir: Path) -> None:
        """Write session to disk so it survives server restarts."""
        try:
            session = self.get(session_id)
        except KeyError:
            return
        sidecar = self._live_snapshot(session_id)
        path = self._live_session_path(lineage_dir, session.object_id)
        path.write_text(json.dumps(sidecar, indent=2))

    def load_live(self, lineage_dir: Path, object_id: str) -> dict[str, Any] | None:
        """Read persisted session from disk and return summary; does not restore into RAM."""
        path = self._live_session_path(lineage_dir, object_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
        except Exception:
            return None
        return data

    def restore_live(self, lineage_dir: Path, object_id: str) -> SessionState | None:
        """Restore persisted session from disk into RAM."""
        data = self.load_live(lineage_dir, object_id)
        if data is None:
            return None
        session_id = str(data.get("session_id", ""))
        embedding_key = str(data.get("embedding_key", ""))
        cluster_key = str(data.get("cluster_key", ""))
        if not session_id:
            return None

        session = SessionState(
            session_id=session_id,
            object_id=object_id,
            embedding_key=embedding_key,
            cluster_key=cluster_key,
        )
        session.seed_display_names = {str(k): str(v) for k, v in (data.get("labels") or {}).items()}

        for polygon_data in data.get("polygons") or []:
            batch = PolygonSeedBatch(
                polygon_id=str(polygon_data["polygon_id"]),
                label=str(polygon_data["label"]),
                display_name=polygon_data.get("display_name"),
                notes=polygon_data.get("notes"),
                cell_indices=np.array([], dtype=int),
                vertices=polygon_data.get("vertices", []),
            )
            session.polygon_batches.append(batch)

        for str_idx, label in (data.get("seed_labels") or {}).items():
            try:
                idx = int(str_idx)
                session.seed_labels[idx] = str(label)
            except (ValueError, TypeError):
                pass

        for str_idx, poly_ids in (data.get("seed_polygon_ids") or {}).items():
            try:
                idx = int(str_idx)
                session.seed_polygon_ids[idx] = set(poly_ids)
            except (ValueError, TypeError):
                pass

        propagation_data = data.get("last_propagation") or {}
        if "assigned_labels" in propagation_data:
            try:
                session.last_propagation = PropagationSnapshot(
                    label_names=list(propagation_data["label_names"]),
                    assigned_labels=np.array(propagation_data["assigned_labels"], dtype=object),
                    assigned_scores=np.array(propagation_data["assigned_scores"], dtype=float),
                    assigned_margins=np.array(propagation_data["assigned_margins"], dtype=float),
                    eligible_mask=np.array(propagation_data["eligible_mask"], dtype=bool),
                    assigned_mask=np.array(propagation_data["assigned_mask"], dtype=bool),
                    method=str(propagation_data.get("method", "")),
                    scope=str(propagation_data.get("scope", "")),
                    min_score=float(propagation_data.get("min_score", 0.0)),
                    min_margin=float(propagation_data.get("min_margin", 0.0)),
                    annotate_all=bool(propagation_data.get("annotate_all", False)),
                    graph_smoothing=float(propagation_data.get("graph_smoothing", 0.0)),
                    cluster_key=str(propagation_data.get("cluster_key", "")),
                )
            except (KeyError, ValueError, TypeError):
                session.last_propagation = None

        self._sessions[session_id] = session
        return session

    def clear_live(self, lineage_dir: Path, object_id: str) -> None:
        """Delete the persisted live session file and evict any matching RAM session."""
        path = self._live_session_path(lineage_dir, object_id)
        if path.exists():
            try:
                data = json.loads(path.read_text())
                stale_id = data.get("session_id")
                if stale_id:
                    self._sessions.pop(stale_id, None)
            except Exception:
                pass
        path.unlink(missing_ok=True)

    def live_session_summary(self, lineage_dir: Path, object_id: str) -> dict[str, Any]:
        """Return lightweight summary for UI restore prompt.

        Returns `available: False` if no file exists, or if the persisted
        session is already active in RAM (user already restored it this run).
        """
        data = self.load_live(lineage_dir, object_id)
        if data is None:
            return {"object_id": object_id, "available": False}

        # If the session from disk is already loaded in RAM, don't offer restore
        persisted_id = data.get("session_id")
        if persisted_id and persisted_id in self._sessions:
            session = self._sessions[persisted_id]
            has_propagation = session.last_propagation is not None
            label_counts = Counter(session.seed_labels.values())
            return {
                "object_id": object_id,
                "available": False,  # already active — banner should not show
                "session_id": persisted_id,
                "n_seed_cells": len(session.seed_labels),
                "n_polygons": len(session.polygon_batches),
                "labels": dict(sorted(label_counts.items())),
                "has_propagation": has_propagation,
            }

        seed_labels = data.get("seed_labels") or {}
        polygons = data.get("polygons") or []
        label_counts = Counter(seed_labels.values())
        return {
            "object_id": object_id,
            "available": True,
            "session_id": persisted_id,
            "n_seed_cells": len(seed_labels),
            "n_polygons": len(polygons),
            "labels": dict(sorted(label_counts.items())),
            "embedding_key": data.get("embedding_key"),
            "cluster_key": data.get("cluster_key"),
            "has_propagation": data.get("last_propagation") is not None,
        }


session_store = SessionStore()
