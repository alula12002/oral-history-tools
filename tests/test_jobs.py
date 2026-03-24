import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.jobs import (
    InMemoryJobStore,
    cleanup_old_cache,
    load_job_cache,
    restore_cached_jobs,
    save_job_cache,
)
from backend.schemas import JobDetail, JobStatus


def _make_job(job_id="abc123", status=JobStatus.completed, step="transcribe"):
    return JobDetail(
        job_id=job_id,
        status=status,
        step=step,
        progress=1.0,
        created_at="2026-01-01T00:00:00+00:00",
    )


class TestSaveLoadCache(unittest.TestCase):
    """Test saving and loading job cache to/from disk."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_save_and_load_job(self):
        """Save a job, then load it back and verify fields match."""
        with patch("config.CACHE_DIR", self.tmpdir):
            job = _make_job()
            save_job_cache("abc123", job)

            result = load_job_cache("abc123")
            self.assertIsNotNone(result)
            self.assertEqual(result["job"].job_id, "abc123")
            self.assertEqual(result["job"].status, JobStatus.completed)
            self.assertIsNone(result["raw_results"])
            self.assertIsNone(result["refined_text"])

    def test_save_and_load_with_raw_results(self):
        """Cache should persist raw transcription results."""
        with patch("config.CACHE_DIR", self.tmpdir):
            job = _make_job()
            raw = [{"sequence": 1, "text": "Hello", "status": "ok"}]
            save_job_cache("abc123", job, raw_results=raw)

            result = load_job_cache("abc123")
            self.assertIsNotNone(result["raw_results"])
            self.assertEqual(len(result["raw_results"]), 1)
            self.assertEqual(result["raw_results"][0]["text"], "Hello")

    def test_save_and_load_with_refined_text(self):
        """Cache should persist refined text."""
        with patch("config.CACHE_DIR", self.tmpdir):
            job = _make_job(step="refine")
            save_job_cache("abc123", job, refined_text="Refined output")

            result = load_job_cache("abc123")
            self.assertEqual(result["refined_text"], "Refined output")

    def test_load_nonexistent_returns_none(self):
        """Loading a non-existent job should return None."""
        with patch("config.CACHE_DIR", self.tmpdir):
            result = load_job_cache("nonexistent")
            self.assertIsNone(result)

    def test_cache_file_structure(self):
        """Verify the expected file structure on disk."""
        with patch("config.CACHE_DIR", self.tmpdir):
            job = _make_job()
            raw = [{"sequence": 1, "text": "Hello", "status": "ok"}]
            save_job_cache("abc123", job, raw_results=raw, refined_text="Final")

            cache_dir = Path(self.tmpdir) / "abc123"
            self.assertTrue((cache_dir / "job.json").exists())
            self.assertTrue((cache_dir / "raw_results.json").exists())
            self.assertTrue((cache_dir / "refined.txt").exists())


class TestRestoreCachedJobs(unittest.TestCase):
    """Test restoring jobs from cache on startup."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_restore_completed_jobs(self):
        """Completed jobs should be restored to the store."""
        with patch("config.CACHE_DIR", self.tmpdir):
            # Save two jobs
            job1 = _make_job("job1", status=JobStatus.completed)
            job2 = _make_job("job2", status=JobStatus.completed, step="refine")
            raw1 = [{"sequence": 1, "text": "Page 1", "status": "ok"}]
            save_job_cache("job1", job1, raw_results=raw1)
            save_job_cache("job2", job2, refined_text="Done")

            store = InMemoryJobStore()
            restored_raw = restore_cached_jobs(store)

            # Both jobs should be in the store
            self.assertIsNotNone(store.get("job1"))
            self.assertIsNotNone(store.get("job2"))
            # Raw results should be returned for job1
            self.assertIn("job1", restored_raw)
            self.assertEqual(len(restored_raw["job1"]), 1)

    def test_skip_processing_jobs(self):
        """Jobs that were mid-processing should NOT be restored."""
        with patch("config.CACHE_DIR", self.tmpdir):
            job = _make_job("inprog", status=JobStatus.processing)
            save_job_cache("inprog", job)

            store = InMemoryJobStore()
            restore_cached_jobs(store)

            self.assertIsNone(store.get("inprog"))

    def test_empty_cache_dir(self):
        """Empty cache dir should restore nothing without error."""
        with patch("config.CACHE_DIR", self.tmpdir):
            store = InMemoryJobStore()
            restored_raw = restore_cached_jobs(store)
            self.assertEqual(restored_raw, {})

    def test_nonexistent_cache_dir(self):
        """Non-existent cache dir should return empty without error."""
        with patch("config.CACHE_DIR", os.path.join(self.tmpdir, "nope")):
            store = InMemoryJobStore()
            restored_raw = restore_cached_jobs(store)
            self.assertEqual(restored_raw, {})


class TestCleanupOldCache(unittest.TestCase):
    """Test cleanup of stale cache entries."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_removes_old_entries(self):
        """Entries older than max_age_days should be removed."""
        with patch("config.CACHE_DIR", self.tmpdir), \
             patch("config.CACHE_MAX_AGE_DAYS", 30):
            # Create a cache entry
            job = _make_job("old_job")
            save_job_cache("old_job", job)

            # Backdate the file to 31 days ago
            job_path = Path(self.tmpdir) / "old_job" / "job.json"
            old_time = time.time() - (31 * 86400)
            os.utime(job_path, (old_time, old_time))

            removed = cleanup_old_cache(max_age_days=30)
            self.assertEqual(removed, 1)
            self.assertFalse((Path(self.tmpdir) / "old_job").exists())

    def test_keeps_recent_entries(self):
        """Recent entries should not be removed."""
        with patch("config.CACHE_DIR", self.tmpdir), \
             patch("config.CACHE_MAX_AGE_DAYS", 30):
            job = _make_job("new_job")
            save_job_cache("new_job", job)

            removed = cleanup_old_cache(max_age_days=30)
            self.assertEqual(removed, 0)
            self.assertTrue((Path(self.tmpdir) / "new_job").exists())


if __name__ == "__main__":
    unittest.main()
