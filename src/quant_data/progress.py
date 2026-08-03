from __future__ import annotations

import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, Set, Any

logger = logging.getLogger(__name__)


class ProgressTracker:
    """JSON-based progress tracker for resumable BaoStock downloads."""

    def __init__(self, progress_dir: str) -> None:
        self._dir = Path(progress_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._cache: Dict[str, dict] = {}

    def _path(self, job_name: str) -> Path:
        return self._dir / f"{job_name}.json"

    def load(self, job_name: str) -> dict:
        if job_name in self._cache:
            return self._cache[job_name]
        path = self._path(job_name)
        if path.exists():
            with open(path) as f:
                data = json.load(f)
        else:
            data = {"last_updated": None, "completed": {}, "failed": {}}
        self._cache[job_name] = data
        return data

    def save(self, job_name: str) -> None:
        data = self._cache.get(job_name, {})
        data["last_updated"] = datetime.now().isoformat()
        path = self._path(job_name)
        with open(path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def is_completed(self, job_name: str, symbol: str, year: int) -> bool:
        data = self.load(job_name)
        return f"{symbol}:{year}" in data.get("completed", {})

    def mark_completed(self, job_name: str, symbol: str, year: int, row_count: int = 0) -> None:
        data = self.load(job_name)
        data.setdefault("completed", {})[f"{symbol}:{year}"] = {
            "row_count": row_count,
            "completed_at": datetime.now().isoformat(),
        }
        # Remove from failed if it was there
        data.get("failed", {}).pop(f"{symbol}:{year}", None)
        self.save(job_name)

    def mark_failed(self, job_name: str, symbol: str, year: int, error: str) -> None:
        data = self.load(job_name)
        key = f"{symbol}:{year}"
        failed = data.setdefault("failed", {})
        attempts = failed.get(key, {}).get("attempts", 0) + 1
        failed[key] = {"error": str(error), "attempts": attempts}
        self.save(job_name)

    def get_completed_symbols(self, job_name: str) -> Set[str]:
        data = self.load(job_name)
        return {k.split(":")[0] for k in data.get("completed", {})}

    def get_failed(self, job_name: str) -> Dict[str, Any]:
        data = self.load(job_name)
        return data.get("failed", {})

    def get_resume_point(self, job_name: str, symbol: str) -> Optional[str]:
        """Get last completed year for a symbol."""
        data = self.load(job_name)
        completed = data.get("completed", {})
        years = []
        for key in completed:
            parts = key.split(":")
            if parts[0] == symbol:
                try:
                    years.append(int(parts[1]))
                except (ValueError, IndexError):
                    pass
        return str(max(years)) if years else None

    def reset(self, job_name: str) -> None:
        path = self._path(job_name)
        if path.exists():
            path.unlink()
        self._cache.pop(job_name, None)
