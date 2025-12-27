from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from arp_standard_model import NodeRun, NodeRunState, NodeTypeRef, Run, RunState
from arp_standard_server import AuthSettings
from jarvis_run_store.config import RunStoreConfig, run_store_config_from_env
from jarvis_run_store.errors import ConflictError, NotFoundError, StorageFullError
from jarvis_run_store.service import create_app
from jarvis_run_store.sqlite import SqliteRunStore
from jarvis_run_store.utils import (
    DEFAULT_DEV_KEYCLOAK_ISSUER,
    auth_settings_from_env_or_dev_secure,
    decode_page_token,
)


def _make_run(run_id: str = "run_1", root_node_run_id: str = "node_1") -> Run:
    return Run(run_id=run_id, root_node_run_id=root_node_run_id, state=RunState.running)


def _make_node_run(node_run_id: str = "node_1", run_id: str = "run_1") -> NodeRun:
    return NodeRun(
        node_run_id=node_run_id,
        run_id=run_id,
        state=NodeRunState.running,
        node_type_ref=NodeTypeRef(node_type_id="atomic.echo", version="0.1.0"),
    )


def test_invalid_sqlite_url() -> None:
    config = RunStoreConfig(db_url="postgres://db", max_size_mb=None)
    with pytest.raises(ValueError):
        _ = config.db_path


def test_missing_sqlite_path() -> None:
    config = RunStoreConfig(db_url="sqlite:///", max_size_mb=None)
    with pytest.raises(ValueError):
        _ = config.db_path


def test_config_from_env(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("JARVIS_RUN_STORE_DB_URL", f"sqlite:///{tmp_path / 'runs.sqlite'}")
    monkeypatch.setenv("JARVIS_RUN_STORE_MAX_SIZE_MB", "5")
    config = run_store_config_from_env()
    assert config.db_url.endswith("runs.sqlite")
    assert config.max_size_mb == 5


def test_auth_settings_default(monkeypatch) -> None:
    for key in list(os.environ):
        if key.startswith("ARP_AUTH_"):
            monkeypatch.delenv(key, raising=False)
    settings = auth_settings_from_env_or_dev_secure()
    assert settings.mode == "required"
    assert settings.issuer == DEFAULT_DEV_KEYCLOAK_ISSUER


def test_auth_settings_from_env(monkeypatch) -> None:
    monkeypatch.setenv("ARP_AUTH_MODE", "disabled")
    settings = auth_settings_from_env_or_dev_secure()
    assert settings.mode == "disabled"


def test_decode_page_token_invalid() -> None:
    with pytest.raises(ValueError):
        decode_page_token("not-base64")


def test_idempotency_conflicts(tmp_path) -> None:
    config = RunStoreConfig(db_url=f"sqlite:///{tmp_path / 'run_store.sqlite'}", max_size_mb=None)
    store = SqliteRunStore(config)

    run_one = _make_run(run_id="run_1")
    store.create_run(run_one, idempotency_key="key-1")
    existing = store.create_run(run_one, idempotency_key="key-1")
    assert existing.run_id == "run_1"

    run_two = _make_run(run_id="run_2")
    with pytest.raises(ConflictError):
        store.create_run(run_two, idempotency_key="key-1")

    with pytest.raises(ConflictError):
        store.create_run(run_one)


def test_missing_run_and_node_run(tmp_path) -> None:
    config = RunStoreConfig(db_url=f"sqlite:///{tmp_path / 'run_store.sqlite'}", max_size_mb=None)
    store = SqliteRunStore(config)

    with pytest.raises(NotFoundError):
        store.get_run("missing")

    with pytest.raises(NotFoundError):
        store.get_node_run("missing")


def test_update_id_mismatch(tmp_path) -> None:
    config = RunStoreConfig(db_url=f"sqlite:///{tmp_path / 'run_store.sqlite'}", max_size_mb=None)
    store = SqliteRunStore(config)

    run = _make_run(run_id="run_1")
    store.create_run(run)

    with pytest.raises(ConflictError):
        store.update_run("run_2", run)

    with pytest.raises(NotFoundError):
        store.update_run("missing", _make_run(run_id="missing"))

    node_run = _make_node_run(node_run_id="node_1")
    store.create_node_run(node_run)

    with pytest.raises(ConflictError):
        store.update_node_run("node_2", node_run)

    with pytest.raises(NotFoundError):
        store.update_node_run("missing", _make_node_run(node_run_id="missing", run_id="run_1"))


def test_storage_full(tmp_path) -> None:
    config = RunStoreConfig(db_url=f"sqlite:///{tmp_path / 'run_store.sqlite'}", max_size_mb=0)
    store = SqliteRunStore(config)

    with pytest.raises(StorageFullError):
        store.create_run(_make_run())


def test_invalid_page_token_returns_422(tmp_path) -> None:
    config = RunStoreConfig(db_url=f"sqlite:///{tmp_path / 'run_store.sqlite'}", max_size_mb=None)
    app = create_app(config, auth_settings=AuthSettings(mode="disabled"))
    client = TestClient(app)

    resp = client.get("/v1/runs/run_1/node-runs", params={"page_token": "bad-token"})
    assert resp.status_code == 422


def test_service_conflict_and_not_found(tmp_path) -> None:
    config = RunStoreConfig(db_url=f"sqlite:///{tmp_path / 'run_store.sqlite'}", max_size_mb=None)
    app = create_app(config, auth_settings=AuthSettings(mode="disabled"))
    client = TestClient(app)

    run = _make_run(run_id="run_1")
    create_resp = client.post("/v1/runs", json={"run": run.model_dump(mode="json")})
    assert create_resp.status_code == 200

    conflict_resp = client.put(
        "/v1/runs/run_1",
        json={"run": _make_run(run_id="run_2").model_dump(mode="json")},
    )
    assert conflict_resp.status_code == 409

    missing_resp = client.put(
        "/v1/runs/missing",
        json={"run": _make_run(run_id="missing").model_dump(mode="json")},
    )
    assert missing_resp.status_code == 404

    node_run = _make_node_run(node_run_id="node_1", run_id="run_1")
    client.post("/v1/node-runs", json={"node_run": node_run.model_dump(mode="json")})

    node_conflict = client.put(
        "/v1/node-runs/node_1",
        json={"node_run": _make_node_run(node_run_id="node_2", run_id="run_1").model_dump(mode="json")},
    )
    assert node_conflict.status_code == 409

    node_missing = client.put(
        "/v1/node-runs/missing",
        json={"node_run": _make_node_run(node_run_id="missing", run_id="run_1").model_dump(mode="json")},
    )
    assert node_missing.status_code == 404


def test_service_storage_full_returns_507(tmp_path) -> None:
    config = RunStoreConfig(db_url=f"sqlite:///{tmp_path / 'run_store.sqlite'}", max_size_mb=0)
    app = create_app(config, auth_settings=AuthSettings(mode="disabled"))
    client = TestClient(app)

    run = _make_run(run_id="run_1")
    resp = client.post("/v1/runs", json={"run": run.model_dump(mode="json")})
    assert resp.status_code == 507

    node_run = _make_node_run(node_run_id="node_1", run_id="run_1")
    resp = client.post("/v1/node-runs", json={"node_run": node_run.model_dump(mode="json")})
    assert resp.status_code == 507
