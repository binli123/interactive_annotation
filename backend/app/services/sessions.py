from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import json
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


session_store = SessionStore()
