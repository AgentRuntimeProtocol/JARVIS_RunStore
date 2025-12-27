from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RunStoreConfig:
    db_url: str
    max_size_mb: int | None

    @property
    def db_path(self) -> Path:
        return Path(_sqlite_path(self.db_url))


def run_store_config_from_env() -> RunStoreConfig:
    db_url = os.getenv("JARVIS_RUN_STORE_DB_URL", "sqlite:///./runs/jarvis_run_store.sqlite")
    max_size_raw = os.getenv("JARVIS_RUN_STORE_MAX_SIZE_MB")
    max_size = int(max_size_raw) if max_size_raw else None
    return RunStoreConfig(db_url=db_url, max_size_mb=max_size)


def _sqlite_path(db_url: str) -> str:
    prefix = "sqlite:///"
    if not db_url.startswith(prefix):
        raise ValueError("Only sqlite:/// URLs are supported for JARVIS Run Store.")
    path = db_url[len(prefix) :]
    if not path:
        raise ValueError("SQLite URL must include a file path.")
    return path
