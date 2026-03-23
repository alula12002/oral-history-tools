"""Job store for tracking async processing jobs.

In-memory store for local development. For production, swap with
a persistent implementation (Redis, Supabase, Postgres).
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Optional

from backend.schemas import JobDetail, JobStatus


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


# Default store instance
job_store = InMemoryJobStore()
