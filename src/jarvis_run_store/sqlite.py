from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from collections.abc import Sequence
from typing import Iterator

from arp_standard_model import NodeRun, Run

from .config import RunStoreConfig
from .errors import ConflictError, NotFoundError, StorageFullError
from .utils import now


@dataclass(frozen=True)
class ListNodeRunsResult:
    items: list[NodeRun]
    next_offset: int | None


class SqliteRunStore:
    def __init__(self, config: RunStoreConfig) -> None:
        self._db_path = config.db_path
        self._max_size_mb = config.max_size_mb
        self._ensure_db_dir()
        self._init_db()

    def create_run(self, run: Run, *, idempotency_key: str | None = None) -> Run:
        self._check_size()
        run_json = _encode_model(run)
        timestamp = now()
        with self._connect() as conn:
            if idempotency_key:
                existing = _fetch_one(conn, "SELECT run_id, run_json FROM runs WHERE idempotency_key = ?", (idempotency_key,))
                if existing:
                    existing_run = _decode_run(existing["run_json"])
                    if existing_run.run_id != run.run_id:
                        raise ConflictError("Idempotency key already used for a different run_id.")
                    return existing_run
            try:
                conn.execute(
                    "INSERT INTO runs (run_id, run_json, idempotency_key, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (run.run_id, run_json, idempotency_key, timestamp, timestamp),
                )
            except sqlite3.IntegrityError as exc:
                raise ConflictError("Run already exists.") from exc
        return run

    def get_run(self, run_id: str) -> Run:
        with self._connect() as conn:
            row = _fetch_one(conn, "SELECT run_json FROM runs WHERE run_id = ?", (run_id,))
        if not row:
            raise NotFoundError("Run not found.")
        return _decode_run(row["run_json"])

    def update_run(self, run_id: str, run: Run) -> Run:
        if run.run_id != run_id:
            raise ConflictError("run_id path parameter does not match payload.")
        run_json = _encode_model(run)
        timestamp = now()
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE runs SET run_json = ?, updated_at = ? WHERE run_id = ?",
                (run_json, timestamp, run_id),
            )
        if cursor.rowcount == 0:
            raise NotFoundError("Run not found.")
        return run

    def create_node_run(self, node_run: NodeRun, *, idempotency_key: str | None = None) -> NodeRun:
        self._check_size()
        node_run_json = _encode_model(node_run)
        timestamp = now()
        with self._connect() as conn:
            if idempotency_key:
                existing = _fetch_one(
                    conn,
                    "SELECT node_run_id, node_run_json FROM node_runs WHERE idempotency_key = ?",
                    (idempotency_key,),
                )
                if existing:
                    existing_node_run = _decode_node_run(existing["node_run_json"])
                    if existing_node_run.node_run_id != node_run.node_run_id:
                        raise ConflictError("Idempotency key already used for a different node_run_id.")
                    return existing_node_run
            try:
                conn.execute(
                    "INSERT INTO node_runs (node_run_id, run_id, node_run_json, idempotency_key, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (node_run.node_run_id, node_run.run_id, node_run_json, idempotency_key, timestamp, timestamp),
                )
            except sqlite3.IntegrityError as exc:
                raise ConflictError("NodeRun already exists.") from exc
        return node_run

    def get_node_run(self, node_run_id: str) -> NodeRun:
        with self._connect() as conn:
            row = _fetch_one(conn, "SELECT node_run_json FROM node_runs WHERE node_run_id = ?", (node_run_id,))
        if not row:
            raise NotFoundError("NodeRun not found.")
        return _decode_node_run(row["node_run_json"])

    def update_node_run(self, node_run_id: str, node_run: NodeRun) -> NodeRun:
        if node_run.node_run_id != node_run_id:
            raise ConflictError("node_run_id path parameter does not match payload.")
        node_run_json = _encode_model(node_run)
        timestamp = now()
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE node_runs SET node_run_json = ?, updated_at = ? WHERE node_run_id = ?",
                (node_run_json, timestamp, node_run_id),
            )
        if cursor.rowcount == 0:
            raise NotFoundError("NodeRun not found.")
        return node_run

    def list_node_runs(self, run_id: str, *, limit: int, offset: int) -> ListNodeRunsResult:
        with self._connect() as conn:
            rows = list(
                conn.execute(
                    "SELECT node_run_json FROM node_runs WHERE run_id = ? ORDER BY created_at, node_run_id LIMIT ? OFFSET ?",
                    (run_id, limit, offset),
                )
            )
        items = [_decode_node_run(row["node_run_json"]) for row in rows]
        next_offset = offset + len(items) if len(items) == limit else None
        return ListNodeRunsResult(items=items, next_offset=next_offset)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _ensure_db_dir(self) -> None:
        if self._db_path.parent:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS runs ("
                "run_id TEXT PRIMARY KEY, "
                "run_json TEXT NOT NULL, "
                "idempotency_key TEXT, "
                "created_at TEXT NOT NULL, "
                "updated_at TEXT NOT NULL"
                ")"
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_idempotency ON runs(idempotency_key) "
                "WHERE idempotency_key IS NOT NULL"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS node_runs ("
                "node_run_id TEXT PRIMARY KEY, "
                "run_id TEXT NOT NULL, "
                "node_run_json TEXT NOT NULL, "
                "idempotency_key TEXT, "
                "created_at TEXT NOT NULL, "
                "updated_at TEXT NOT NULL"
                ")"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_node_runs_run_id ON node_runs(run_id)")
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_node_runs_idempotency ON node_runs(idempotency_key) "
                "WHERE idempotency_key IS NOT NULL"
            )

    def _check_size(self) -> None:
        if self._max_size_mb is None or not self._db_path.exists():
            return
        size_mb = self._db_path.stat().st_size / (1024 * 1024)
        if size_mb > self._max_size_mb:
            raise StorageFullError("Run store exceeds configured max size.")


def _fetch_one(conn: sqlite3.Connection, query: str, params: Sequence[object]) -> sqlite3.Row | None:
    cursor = conn.execute(query, params)
    return cursor.fetchone()


def _encode_model(model: Run | NodeRun) -> str:
    payload = model.model_dump(mode="json")
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=True)


def _decode_run(raw: str) -> Run:
    return Run.model_validate(json.loads(raw))


def _decode_node_run(raw: str) -> NodeRun:
    return NodeRun.model_validate(json.loads(raw))
