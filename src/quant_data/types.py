from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class DownloadStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class DownloadTask:
    symbol: str
    start_date: str
    end_date: str
    frequency: str
    source: str
    interface: str


@dataclass
class DownloadResult:
    task: DownloadTask
    status: DownloadStatus
    rows_fetched: int = 0
    rows_written: int = 0
    file_path: str = ""
    error: str = ""
    elapsed_seconds: float = 0.0


@dataclass
class SyncMeta:
    table_name: str
    last_date: Optional[str] = None
    updated_at: Optional[str] = None
