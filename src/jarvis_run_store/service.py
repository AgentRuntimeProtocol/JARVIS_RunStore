from __future__ import annotations

from typing import Annotated
from datetime import datetime, timezone

from arp_standard_model import Health, NodeRun, Run, Status, VersionInfo
from arp_standard_server import AuthSettings
from arp_standard_server.auth import register_auth_middleware
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from . import __version__
from .config import RunStoreConfig, run_store_config_from_env
from .errors import ConflictError, NotFoundError, StorageFullError
from .sqlite import ListNodeRunsResult, SqliteRunStore
from .utils import (
    auth_settings_from_env_or_dev_secure,
    decode_page_token,
    encode_page_token,
    now,
)


class CreateRunRequest(BaseModel):
    run: Run
    idempotency_key: str | None = None


class RunResponse(BaseModel):
    run: Run


class CreateNodeRunRequest(BaseModel):
    node_run: NodeRun
    idempotency_key: str | None = None


class NodeRunResponse(BaseModel):
    node_run: NodeRun


class ListNodeRunsResponse(BaseModel):
    items: list[NodeRun]
    next_token: str | None = None


def create_app(
    config: RunStoreConfig | None = None,
    auth_settings: AuthSettings | None = None,
) -> FastAPI:
    cfg = config or run_store_config_from_env()
    store = SqliteRunStore(cfg)

    app = FastAPI(title="JARVIS Run Store", version=__version__)
    register_auth_middleware(app, settings=auth_settings or auth_settings_from_env_or_dev_secure())

    @app.get("/v1/health", response_model=Health)
    async def health() -> Health:
        return Health(status=Status.ok, time=datetime.now(timezone.utc))

    @app.get("/v1/version", response_model=VersionInfo)
    async def version() -> VersionInfo:
        return VersionInfo(
            service_name="arp-jarvis-runstore",
            service_version=__version__,
            supported_api_versions=["v1"],
        )

    @app.post("/v1/runs", response_model=RunResponse)
    async def create_run(request: CreateRunRequest) -> RunResponse:
        try:
            run = store.create_run(request.run, idempotency_key=request.idempotency_key)
        except ConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except StorageFullError as exc:
            raise HTTPException(status_code=507, detail=str(exc)) from exc
        return RunResponse(run=run)

    @app.get("/v1/runs/{run_id}", response_model=RunResponse)
    async def get_run(run_id: str) -> RunResponse:
        try:
            run = store.get_run(run_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return RunResponse(run=run)

    @app.put("/v1/runs/{run_id}", response_model=RunResponse)
    async def update_run(run_id: str, request: RunResponse) -> RunResponse:
        try:
            run = store.update_run(run_id, request.run)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return RunResponse(run=run)

    @app.post("/v1/node-runs", response_model=NodeRunResponse)
    async def create_node_run(request: CreateNodeRunRequest) -> NodeRunResponse:
        try:
            node_run = store.create_node_run(request.node_run, idempotency_key=request.idempotency_key)
        except ConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except StorageFullError as exc:
            raise HTTPException(status_code=507, detail=str(exc)) from exc
        return NodeRunResponse(node_run=node_run)

    @app.get("/v1/node-runs/{node_run_id}", response_model=NodeRunResponse)
    async def get_node_run(node_run_id: str) -> NodeRunResponse:
        try:
            node_run = store.get_node_run(node_run_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return NodeRunResponse(node_run=node_run)

    @app.put("/v1/node-runs/{node_run_id}", response_model=NodeRunResponse)
    async def update_node_run(node_run_id: str, request: NodeRunResponse) -> NodeRunResponse:
        try:
            node_run = store.update_node_run(node_run_id, request.node_run)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return NodeRunResponse(node_run=node_run)

    @app.get("/v1/runs/{run_id}/node-runs", response_model=ListNodeRunsResponse)
    async def list_node_runs(
        run_id: str,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        page_token: str | None = None,
    ) -> ListNodeRunsResponse:
        if page_token:
            try:
                offset = decode_page_token(page_token)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        else:
            offset = 0
        result: ListNodeRunsResult = store.list_node_runs(run_id, limit=limit, offset=offset)
        next_token = encode_page_token(result.next_offset) if result.next_offset is not None else None
        return ListNodeRunsResponse(items=result.items, next_token=next_token)

    return app
