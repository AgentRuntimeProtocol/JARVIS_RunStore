from __future__ import annotations

from fastapi.testclient import TestClient

from arp_standard_model import NodeRun, NodeRunState, NodeTypeRef, Run, RunState
from arp_standard_server import AuthSettings
from jarvis_run_store.config import RunStoreConfig
from jarvis_run_store.service import create_app


def _make_run(run_id: str = "run_1", root_node_run_id: str = "node_1") -> Run:
    return Run(run_id=run_id, root_node_run_id=root_node_run_id, state=RunState.running)


def _make_node_run(node_run_id: str = "node_1", run_id: str = "run_1") -> NodeRun:
    return NodeRun(
        node_run_id=node_run_id,
        run_id=run_id,
        state=NodeRunState.running,
        node_type_ref=NodeTypeRef(node_type_id="jarvis.core.echo", version="0.3.2"),
    )


def test_run_store_roundtrip(tmp_path) -> None:
    config = RunStoreConfig(db_url=f"sqlite:///{tmp_path / 'run_store.sqlite'}", max_size_mb=None)
    app = create_app(config, auth_settings=AuthSettings(mode="disabled"))
    client = TestClient(app)

    run = _make_run()
    create_resp = client.post("/v1/runs", json={"run": run.model_dump(mode="json")})
    assert create_resp.status_code == 200
    assert create_resp.json()["run"]["run_id"] == "run_1"

    get_resp = client.get("/v1/runs/run_1")
    assert get_resp.status_code == 200

    update_run = _make_run()
    update_resp = client.put("/v1/runs/run_1", json={"run": update_run.model_dump(mode="json")})
    assert update_resp.status_code == 200


def test_node_run_listing_with_pagination(tmp_path) -> None:
    config = RunStoreConfig(db_url=f"sqlite:///{tmp_path / 'run_store.sqlite'}", max_size_mb=None)
    app = create_app(config, auth_settings=AuthSettings(mode="disabled"))
    client = TestClient(app)

    run = _make_run()
    client.post("/v1/runs", json={"run": run.model_dump(mode="json")})

    node_one = _make_node_run(node_run_id="node_1")
    node_two = _make_node_run(node_run_id="node_2")
    client.post("/v1/node-runs", json={"node_run": node_one.model_dump(mode="json")})
    client.post("/v1/node-runs", json={"node_run": node_two.model_dump(mode="json")})

    first_page = client.get("/v1/runs/run_1/node-runs", params={"limit": 1})
    assert first_page.status_code == 200
    payload = first_page.json()
    assert len(payload["items"]) == 1
    assert payload["next_token"]

    second_page = client.get(
        "/v1/runs/run_1/node-runs",
        params={"limit": 1, "page_token": payload["next_token"]},
    )
    assert second_page.status_code == 200
    assert len(second_page.json()["items"]) == 1
