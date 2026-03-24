"""Job store for tracking async processing jobs.

In-memory store with disk-based caching for persistence across restarts.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from backend.schemas import JobDetail, JobStatus

logger = logging.getLogger("oral-history-tools")


class InMemoryJobStore:
    """Thread-safe in-memory job store.

    All operations are protected by a lock to prevent race conditions
    when background threads update job state while the main thread reads.
    """

    def __init__(self) -> None:
        self._jobs: dict[str, JobDetail] = {}
        self._lock = threading.Lock()

    def create(self) -> JobDetail:
        job_id = uuid.uuid4().hex[:12]
        job = JobDetail(
            job_id=job_id,
            status=JobStatus.pending,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        with self._lock:
            self._jobs[job_id] = job
        return job

    def get(self, job_id: str) -> Optional[JobDetail]:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job_id: str, **kwargs) -> JobDetail:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(f"Job {job_id} not found")
            updated = job.model_copy(update=kwargs)
            self._jobs[job_id] = updated
            return updated

    def delete(self, job_id: str) -> bool:
        with self._lock:
            return self._jobs.pop(job_id, None) is not None

    def list_all(self) -> list[JobDetail]:
        with self._lock:
            return sorted(
                self._jobs.values(),
                key=lambda j: j.created_at,
                reverse=True,
            )

    def restore(self, job: JobDetail) -> None:
        """Restore a job from cache (used during startup)."""
        with self._lock:
            self._jobs[job.job_id] = job


def save_job_cache(job_id: str, job_detail: JobDetail,
                   raw_results: list[dict] | None = None,
                   refined_text: str | None = None) -> None:
    """Persist job state to disk for recovery after restart.

    Creates:
        {CACHE_DIR}/{job_id}/job.json       - full job record
        {CACHE_DIR}/{job_id}/raw_results.json - page-by-page transcription (if provided)
        {CACHE_DIR}/{job_id}/refined.txt     - final refined text (if provided)
    """
    from config import CACHE_DIR

    cache_dir = Path(CACHE_DIR) / job_id
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Save job record
    job_path = cache_dir / "job.json"
    job_path.write_text(job_detail.model_dump_json(indent=2), encoding="utf-8")

    # Save raw transcription results
    if raw_results is not None:
        raw_path = cache_dir / "raw_results.json"
        raw_path.write_text(json.dumps(raw_results, indent=2, default=str), encoding="utf-8")

    # Save refined text
    if refined_text is not None:
        refined_path = cache_dir / "refined.txt"
        refined_path.write_text(refined_text, encoding="utf-8")

    logger.debug("Cache saved for job %s", job_id)


def load_job_cache(job_id: str) -> dict | None:
    """Load cached job data from disk.

    Returns:
        Dict with keys 'job', 'raw_results', 'refined_text' or None if not found.
    """
    from config import CACHE_DIR

    cache_dir = Path(CACHE_DIR) / job_id
    job_path = cache_dir / "job.json"

    if not job_path.exists():
        return None

    try:
        job = JobDetail.model_validate_json(job_path.read_text(encoding="utf-8"))

        raw_results = None
        raw_path = cache_dir / "raw_results.json"
        if raw_path.exists():
            raw_results = json.loads(raw_path.read_text(encoding="utf-8"))

        refined_text = None
        refined_path = cache_dir / "refined.txt"
        if refined_path.exists():
            refined_text = refined_path.read_text(encoding="utf-8")

        return {"job": job, "raw_results": raw_results, "refined_text": refined_text}
    except Exception as e:
        logger.warning("Failed to load cache for job %s: %s", job_id, e)
        return None


def restore_cached_jobs(store: InMemoryJobStore) -> dict[str, list[dict]]:
    """Scan cache directory and restore completed jobs to the in-memory store.

    Returns:
        Dict mapping job_id -> raw_results for jobs that have transcription data.
    """
    from config import CACHE_DIR

    cache_root = Path(CACHE_DIR)
    if not cache_root.exists():
        return {}

    restored_raw = {}
    count = 0

    for entry in cache_root.iterdir():
        if not entry.is_dir():
            continue
        job_id = entry.name
        cached = load_job_cache(job_id)
        if cached is None:
            continue

        job = cached["job"]
        # Only restore completed or failed jobs (not in-progress)
        if job.status in (JobStatus.completed, JobStatus.failed):
            store.restore(job)
            if cached["raw_results"]:
                restored_raw[job_id] = cached["raw_results"]
            count += 1

    if count:
        logger.info("Restored %d jobs from cache", count)
    return restored_raw


def cleanup_old_cache(max_age_days: int | None = None) -> int:
    """Remove cache entries older than max_age_days.

    Returns:
        Number of entries removed.
    """
    import shutil

    from config import CACHE_DIR, CACHE_MAX_AGE_DAYS

    if max_age_days is None:
        max_age_days = CACHE_MAX_AGE_DAYS

    cache_root = Path(CACHE_DIR)
    if not cache_root.exists():
        return 0

    cutoff = time.time() - (max_age_days * 86400)
    removed = 0

    for entry in cache_root.iterdir():
        if not entry.is_dir():
            continue
        job_path = entry / "job.json"
        if not job_path.exists():
            continue
        if job_path.stat().st_mtime < cutoff:
            shutil.rmtree(entry)
            removed += 1
            logger.debug("Removed stale cache: %s", entry.name)

    if removed:
        logger.info("Cleaned up %d stale cache entries (older than %d days)", removed, max_age_days)
    return removed


# Default store instance
job_store = InMemoryJobStore()
