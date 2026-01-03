from __future__ import annotations

import logging
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

logger = logging.getLogger(__name__)


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
    logger.info("Run Store config (db_path=%s, max_size_mb=%s)", cfg.db_path, cfg.max_size_mb)

    app = FastAPI(title="JARVIS Run Store", version=__version__)
    auth_settings = auth_settings or auth_settings_from_env_or_dev_secure()
    logger.info(
        "Run Store auth settings (mode=%s, issuer=%s)",
        getattr(auth_settings, "mode", None),
        getattr(auth_settings, "issuer", None),
    )
    register_auth_middleware(app, settings=auth_settings)

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
        logger.info(
            "Run create requested (run_id=%s, idempotency=%s)",
            request.run.run_id,
            bool(request.idempotency_key),
        )
        try:
            run = store.create_run(request.run, idempotency_key=request.idempotency_key)
        except ConflictError as exc:
            logger.warning("Run create conflict (run_id=%s)", request.run.run_id)
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except StorageFullError as exc:
            logger.warning("Run store full (run_id=%s)", request.run.run_id)
            raise HTTPException(status_code=507, detail=str(exc)) from exc
        logger.info("Run created (run_id=%s, state=%s)", run.run_id, run.state)
        return RunResponse(run=run)

    @app.get("/v1/runs/{run_id}", response_model=RunResponse)
    async def get_run(run_id: str) -> RunResponse:
        logger.info("Run fetch requested (run_id=%s)", run_id)
        try:
            run = store.get_run(run_id)
        except NotFoundError as exc:
            logger.warning("Run not found (run_id=%s)", run_id)
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return RunResponse(run=run)

    @app.put("/v1/runs/{run_id}", response_model=RunResponse)
    async def update_run(run_id: str, request: RunResponse) -> RunResponse:
        logger.info("Run update requested (run_id=%s)", run_id)
        try:
            run = store.update_run(run_id, request.run)
        except NotFoundError as exc:
            logger.warning("Run update missing (run_id=%s)", run_id)
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ConflictError as exc:
            logger.warning("Run update conflict (run_id=%s)", run_id)
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        logger.info("Run updated (run_id=%s, state=%s)", run.run_id, run.state)
        return RunResponse(run=run)

    @app.post("/v1/node-runs", response_model=NodeRunResponse)
    async def create_node_run(request: CreateNodeRunRequest) -> NodeRunResponse:
        logger.info(
            "NodeRun create requested (node_run_id=%s, run_id=%s, idempotency=%s)",
            request.node_run.node_run_id,
            request.node_run.run_id,
            bool(request.idempotency_key),
        )
        try:
            node_run = store.create_node_run(request.node_run, idempotency_key=request.idempotency_key)
        except ConflictError as exc:
            logger.warning("NodeRun create conflict (node_run_id=%s)", request.node_run.node_run_id)
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except StorageFullError as exc:
            logger.warning("NodeRun store full (node_run_id=%s)", request.node_run.node_run_id)
            raise HTTPException(status_code=507, detail=str(exc)) from exc
        logger.info("NodeRun created (node_run_id=%s, state=%s)", node_run.node_run_id, node_run.state)
        return NodeRunResponse(node_run=node_run)

    @app.get("/v1/node-runs/{node_run_id}", response_model=NodeRunResponse)
    async def get_node_run(node_run_id: str) -> NodeRunResponse:
        logger.info("NodeRun fetch requested (node_run_id=%s)", node_run_id)
        try:
            node_run = store.get_node_run(node_run_id)
        except NotFoundError as exc:
            logger.warning("NodeRun not found (node_run_id=%s)", node_run_id)
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return NodeRunResponse(node_run=node_run)

    @app.put("/v1/node-runs/{node_run_id}", response_model=NodeRunResponse)
    async def update_node_run(node_run_id: str, request: NodeRunResponse) -> NodeRunResponse:
        logger.info("NodeRun update requested (node_run_id=%s)", node_run_id)
        try:
            node_run = store.update_node_run(node_run_id, request.node_run)
        except NotFoundError as exc:
            logger.warning("NodeRun update missing (node_run_id=%s)", node_run_id)
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ConflictError as exc:
            logger.warning("NodeRun update conflict (node_run_id=%s)", node_run_id)
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        logger.info("NodeRun updated (node_run_id=%s, state=%s)", node_run.node_run_id, node_run.state)
        return NodeRunResponse(node_run=node_run)

    @app.get("/v1/runs/{run_id}/node-runs", response_model=ListNodeRunsResponse)
    async def list_node_runs(
        run_id: str,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        page_token: str | None = None,
    ) -> ListNodeRunsResponse:
        logger.info("NodeRun list requested (run_id=%s, limit=%s, page_token=%s)", run_id, limit, bool(page_token))
        if page_token:
            try:
                offset = decode_page_token(page_token)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        else:
            offset = 0
        result: ListNodeRunsResult = store.list_node_runs(run_id, limit=limit, offset=offset)
        next_token = encode_page_token(result.next_offset) if result.next_offset is not None else None
        logger.info(
            "NodeRun list resolved (run_id=%s, count=%s, next_token=%s)",
            run_id,
            len(result.items),
            bool(next_token),
        )
        return ListNodeRunsResponse(items=result.items, next_token=next_token)

    return app
