"""FastAPI backend for oral-history-tools web interface."""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
from pathlib import Path

import anthropic
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from backend.jobs import job_store
from backend.schemas import (
    FileInfo,
    JobStatus,
    PageResult,
    ScanMode,
    StatusResponse,
    UploadResponse,
)

# Ensure project root is on sys.path so we can import ocr/ and shared/
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)

app = FastAPI(title="Oral History Tools API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Temp directory for uploaded files, organized by job_id
UPLOAD_DIR = Path(tempfile.gettempdir()) / "oral-history-uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".pdf"}


def _get_file_type(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        return "pdf"
    return "image"


def _get_job_or_404(job_id: str):
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return job


# --- Health Check ---

@app.get("/api/health")
def health():
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    return {
        "status": "ok",
        "api_key_configured": bool(api_key and not api_key.startswith("sk-placeholder")),
    }


# --- Upload ---

@app.post("/api/upload", response_model=UploadResponse)
async def upload_files(
    files: list[UploadFile],
    mode: ScanMode = ScanMode.handwritten,
    skip_refine: bool = False,
    title: str = "",
):
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    # Validate extensions
    for f in files:
        ext = Path(f.filename or "").suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type: {f.filename}. "
                f"Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
            )

    # Create job
    job = job_store.create()
    job_dir = UPLOAD_DIR / job.job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    # Save files to disk
    file_infos = []
    for f in files:
        filename = f.filename or "unknown"
        dest = job_dir / filename
        content = await f.read()
        dest.write_bytes(content)
        file_infos.append(FileInfo(
            filename=filename,
            size=len(content),
            type=_get_file_type(filename),
        ))

    # Update job with upload info and options
    job_store.update(
        job.job_id,
        status=JobStatus.completed,
        step="upload",
        files=file_infos,
        mode=mode,
        skip_refine=skip_refine,
        title=title or None,
    )

    return UploadResponse(
        job_id=job.job_id,
        status=JobStatus.completed,
        files=file_infos,
    )


# --- Transcribe ---

def _run_transcribe(job_id: str):
    """Background thread: prepare batch and transcribe page-by-page."""
    from config import API_DELAY_SECONDS
    from ocr.scanner import prepare_batch
    from ocr.transcriber import transcribe_page

    try:
        job = job_store.get(job_id)
        job_dir = UPLOAD_DIR / job_id

        # Prepare batch from uploaded files
        batch = prepare_batch(str(job_dir), sort_by="name")
        if not batch:
            job_store.update(job_id, status=JobStatus.failed, error="No valid pages found in uploaded files")
            return

        total_pages = len(batch)
        job_store.update(job_id, num_pages=total_pages)

        # Transcribe page by page for per-page progress
        client = anthropic.Anthropic()
        results = []
        total_tokens = 0

        for i, page in enumerate(batch):
            result = transcribe_page(page, total_pages, mode=job.mode, client=client)
            results.append(result)
            total_tokens += result.get("tokens_used", 0)

            # Update progress after each page
            page_results = [
                PageResult(
                    sequence=r["sequence"],
                    source_file=r["source_file"],
                    source_page=r["source_page"],
                    text=r.get("text"),
                    confidence=r.get("confidence"),
                    status=r.get("status"),
                )
                for r in results
            ]
            job_store.update(
                job_id,
                progress=(i + 1) / total_pages,
                page_results=page_results,
                transcription_tokens=total_tokens,
            )

            # Rate limit between pages
            if i < total_pages - 1:
                time.sleep(API_DELAY_SECONDS)

        ok_count = sum(1 for r in results if r.get("status") == "ok")
        if ok_count == 0:
            job_store.update(job_id, status=JobStatus.failed, error="No pages were successfully transcribed")
            return

        # Store raw results for refine/export steps (held in memory)
        # We store them as a job attribute via the _raw_results dict
        _raw_results[job_id] = results

        job_store.update(job_id, status=JobStatus.completed, step="transcribe", progress=1.0)

    except Exception as e:
        job_store.update(job_id, status=JobStatus.failed, error=str(e))


# In-memory storage for intermediate pipeline data (page results with full text)
_raw_results: dict[str, list[dict]] = {}


@app.post("/api/transcribe/{job_id}")
def start_transcribe(job_id: str):
    job = _get_job_or_404(job_id)

    if job.step == "transcribe" and job.status == JobStatus.processing:
        raise HTTPException(status_code=409, detail="Transcription already in progress")

    job_store.update(job_id, status=JobStatus.processing, step="transcribe", progress=0.0, error=None)

    thread = threading.Thread(target=_run_transcribe, args=(job_id,), daemon=True)
    thread.start()

    return {"job_id": job_id, "status": "processing", "message": "Transcription started"}


# --- Refine ---

def _run_refine(job_id: str):
    """Background thread: refine the transcript using existing refiner."""
    from shared.refiner import chunk_pages, refine_chunk

    try:
        job = job_store.get(job_id)
        results = _raw_results.get(job_id)
        if not results:
            job_store.update(job_id, status=JobStatus.failed, error="No transcription results found. Run transcribe first.")
            return

        if job.skip_refine:
            # Assemble raw text with page markers (same as CLI --skip-refine)
            parts = []
            for r in results:
                if r.get("status") == "ok":
                    header = f"--- PAGE {r['sequence']}: {r['source_file']}, page {r['source_page']} ---"
                    parts.append(f"{header}\n{r['text']}")
            final_text = "\n\n".join(parts)
            job_store.update(
                job_id,
                status=JobStatus.completed,
                step="refine",
                progress=1.0,
                refined_text=final_text,
                refine_stats={"chunks": 0, "tokens_used": 0, "fallback_count": 0, "skipped": True},
            )
            return

        # Chunk and refine
        from config import API_DELAY_SECONDS

        chunks = chunk_pages(results)
        if not chunks:
            job_store.update(job_id, status=JobStatus.failed, error="No valid pages to refine")
            return

        client = anthropic.Anthropic()
        total_chunks = len(chunks)
        refined_parts = []
        total_tokens = 0
        fallback_count = 0

        for i, chunk in enumerate(chunks, start=1):
            result = refine_chunk(chunk, i, total_chunks, client=client)
            refined_parts.append(result["refined_text"])
            total_tokens += result["tokens_used"]
            if result["status"] == "fallback":
                fallback_count += 1

            job_store.update(job_id, progress=i / total_chunks)

            if i < total_chunks:
                time.sleep(API_DELAY_SECONDS)

        refined_text = "\n\n".join(refined_parts)
        job_store.update(
            job_id,
            status=JobStatus.completed,
            step="refine",
            progress=1.0,
            refined_text=refined_text,
            refine_stats={
                "chunks": total_chunks,
                "tokens_used": total_tokens,
                "fallback_count": fallback_count,
            },
        )

    except Exception as e:
        job_store.update(job_id, status=JobStatus.failed, error=str(e))


@app.post("/api/refine/{job_id}")
def start_refine(job_id: str):
    job = _get_job_or_404(job_id)

    if job.step == "refine" and job.status == JobStatus.processing:
        raise HTTPException(status_code=409, detail="Refinement already in progress")

    job_store.update(job_id, status=JobStatus.processing, step="refine", progress=0.0, error=None)

    thread = threading.Thread(target=_run_refine, args=(job_id,), daemon=True)
    thread.start()

    return {"job_id": job_id, "status": "processing", "message": "Refinement started"}


# --- Export ---

@app.get("/api/export/{job_id}")
def export_files(job_id: str):
    """Generate .txt and .docx exports, return download links."""
    from shared.exporter import export_all

    job = _get_job_or_404(job_id)

    if not job.refined_text:
        raise HTTPException(status_code=400, detail="No refined text available. Run transcribe and refine first.")

    # Export to a job-specific output directory
    export_dir = UPLOAD_DIR / job_id / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)

    results = _raw_results.get(job_id, [])
    ok_count = sum(1 for r in results if r.get("status") == "ok")
    source_files = len(set(r["source_file"] for r in results)) if results else 0
    ocr_tokens = job.transcription_tokens
    refine_tokens = (job.refine_stats or {}).get("tokens_used", 0)

    metadata = {
        "pages": ok_count,
        "source_files": source_files,
        "tokens_used": ocr_tokens + refine_tokens,
    }

    paths = export_all(
        job.refined_text,
        output_dir=str(export_dir),
        title=job.title or "Document Transcription",
        metadata=metadata,
    )

    export_paths = {"txt": paths["txt"], "docx": paths["docx"]}
    job_store.update(job_id, step="export", export_paths=export_paths)

    return {
        "job_id": job_id,
        "txt": f"/api/download/{job_id}/txt",
        "docx": f"/api/download/{job_id}/docx",
    }


@app.get("/api/download/{job_id}/{format}")
def download_file(job_id: str, format: str):
    """Serve an exported file for download."""
    job = _get_job_or_404(job_id)

    if not job.export_paths or format not in job.export_paths:
        raise HTTPException(status_code=404, detail=f"No {format} export available")

    filepath = job.export_paths[format]
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Export file not found on disk")

    media_types = {
        "txt": "text/plain",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }

    return FileResponse(
        path=filepath,
        media_type=media_types.get(format, "application/octet-stream"),
        filename=os.path.basename(filepath),
    )


# --- Job Status ---

@app.get("/api/status/{job_id}", response_model=StatusResponse)
def get_status(job_id: str):
    job = _get_job_or_404(job_id)

    return StatusResponse(
        job_id=job.job_id,
        status=job.status,
        step=job.step,
        progress=job.progress,
        error=job.error,
        num_pages=job.num_pages,
        page_results=job.page_results,
        refined_text=job.refined_text,
        export_paths=job.export_paths,
    )


# --- List Jobs ---

@app.get("/api/jobs")
def list_jobs():
    jobs = job_store.list_all()
    return [
        {
            "job_id": j.job_id,
            "status": j.status,
            "step": j.step,
            "created_at": j.created_at,
            "num_files": len(j.files),
            "num_pages": j.num_pages,
        }
        for j in jobs
    ]
