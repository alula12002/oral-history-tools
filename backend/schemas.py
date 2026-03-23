"""Pydantic models for API request/response schemas."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class ScanMode(str, Enum):
    handwritten = "handwritten"
    printed = "printed"
    mixed = "mixed"


# --- Job Detail ---

class FileInfo(BaseModel):
    filename: str
    size: int
    type: str  # "image" or "pdf"


class PageResult(BaseModel):
    sequence: int
    source_file: str
    source_page: int
    text: Optional[str] = None
    confidence: Optional[str] = None
    status: Optional[str] = None


class JobDetail(BaseModel):
    job_id: str
    status: JobStatus
    step: str = ""  # "upload", "transcribe", "refine", "export"
    progress: float = 0.0  # 0.0 to 1.0
    error: Optional[str] = None
    created_at: str = ""

    # Upload results
    files: list[FileInfo] = Field(default_factory=list)
    num_pages: int = 0

    # Transcription results
    page_results: list[PageResult] = Field(default_factory=list)
    transcription_tokens: int = 0

    # Refinement results
    refined_text: Optional[str] = None
    refine_stats: Optional[dict] = None

    # Export results
    export_paths: Optional[dict] = None  # {"txt": path, "docx": path}

    # Options
    mode: ScanMode = ScanMode.handwritten
    skip_refine: bool = False
    title: Optional[str] = None


# --- Responses ---

class UploadResponse(BaseModel):
    job_id: str
    status: JobStatus
    files: list[FileInfo]


class StatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    step: str
    progress: float
    error: Optional[str] = None
    num_pages: int = 0
    page_results: list[PageResult] = Field(default_factory=list)
    refined_text: Optional[str] = None
    export_paths: Optional[dict] = None
