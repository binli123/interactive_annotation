"""Tests for session persistence (F-03)."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from app.services.sessions import SessionStore
from app.models.state import SessionState


@pytest.fixture
def store() -> SessionStore:
    return SessionStore()


@pytest.fixture
def populated_store(tmp_path: Path) -> tuple[SessionStore, str]:
    """A store with one session that has seed labels and polygon batches."""
    s = SessionStore()
    session = s.get_or_create("sess_001", "obj_A", "X_umap", "leiden")
    session.seed_labels = {0: "T_cell", 1: "T_cell", 50: "B_cell"}
    session.seed_display_names = {"T_cell": "T cell", "B_cell": "B cell"}
    return s, "sess_001"


class TestPersist:
    def test_creates_file(self, populated_store, tmp_path):
        store, sid = populated_store
        store.persist(sid, tmp_path)
        expected = tmp_path / ".live_session_obj_A.json"
        assert expected.exists()

    def test_file_is_valid_json(self, populated_store, tmp_path):
        store, sid = populated_store
        store.persist(sid, tmp_path)
        path = tmp_path / ".live_session_obj_A.json"
        data = json.loads(path.read_text())
        assert "session_id" in data
        assert data["session_id"] == "sess_001"

    def test_seed_labels_serialized(self, populated_store, tmp_path):
        store, sid = populated_store
        store.persist(sid, tmp_path)
        path = tmp_path / ".live_session_obj_A.json"
        data = json.loads(path.read_text())
        assert "seed_labels" in data
        assert data["seed_labels"]["0"] == "T_cell"

    def test_missing_session_is_noop(self, tmp_path):
        store = SessionStore()
        store.persist("nonexistent_session", tmp_path)
        assert not any(tmp_path.iterdir())


class TestRestoreLive:
    def test_restores_session(self, populated_store, tmp_path):
        store, sid = populated_store
        store.persist(sid, tmp_path)
        # Fresh store simulates server restart
        fresh = SessionStore()
        restored = fresh.restore_live(tmp_path, "obj_A")
        assert restored is not None
        assert restored.session_id == "sess_001"

    def test_restores_seed_labels(self, populated_store, tmp_path):
        store, sid = populated_store
        store.persist(sid, tmp_path)
        fresh = SessionStore()
        restored = fresh.restore_live(tmp_path, "obj_A")
        assert restored.seed_labels[0] == "T_cell"
        assert restored.seed_labels[50] == "B_cell"

    def test_returns_none_when_no_file(self, tmp_path):
        store = SessionStore()
        result = store.restore_live(tmp_path, "missing_obj")
        assert result is None

    def test_session_added_to_store(self, populated_store, tmp_path):
        store, sid = populated_store
        store.persist(sid, tmp_path)
        fresh = SessionStore()
        fresh.restore_live(tmp_path, "obj_A")
        # Should be retrievable from the store
        session = fresh.get("sess_001")
        assert session is not None


class TestClearLive:
    def test_deletes_file(self, populated_store, tmp_path):
        store, sid = populated_store
        store.persist(sid, tmp_path)
        path = tmp_path / ".live_session_obj_A.json"
        assert path.exists()
        store.clear_live(tmp_path, "obj_A")
        assert not path.exists()

    def test_evicts_ram_session(self, populated_store, tmp_path):
        store, sid = populated_store
        store.persist(sid, tmp_path)
        # Restore into RAM first
        store.restore_live(tmp_path, "obj_A")
        assert "sess_001" in store._sessions
        # clear_live should also remove it from RAM
        store.clear_live(tmp_path, "obj_A")
        assert "sess_001" not in store._sessions

    def test_noop_when_no_file(self, tmp_path):
        store = SessionStore()
        store.clear_live(tmp_path, "nonexistent")  # should not raise


class TestLiveSessionSummary:
    def test_not_available_when_no_file(self, tmp_path):
        store = SessionStore()
        summary = store.live_session_summary(tmp_path, "obj_A")
        assert summary["available"] is False

    def test_available_when_file_exists(self, populated_store, tmp_path):
        store, sid = populated_store
        store.persist(sid, tmp_path)
        # Simulate a fresh store that has not loaded the session into RAM
        fresh = SessionStore()
        summary = fresh.live_session_summary(tmp_path, "obj_A")
        assert summary["available"] is True
        assert summary["n_seed_cells"] == 3
        assert "T_cell" in summary["labels"]

    def test_not_available_when_already_in_ram(self, populated_store, tmp_path):
        store, sid = populated_store
        store.persist(sid, tmp_path)
        # Same store that already holds the session in RAM
        summary = store.live_session_summary(tmp_path, "obj_A")
        assert summary["available"] is False
