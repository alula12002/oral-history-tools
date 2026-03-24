import {
  ExportResponse,
  ScanMode,
  StatusResponse,
  UploadResponse,
} from "./types";

const API_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";

export async function uploadFiles(
  files: File[],
  mode: ScanMode,
  skipRefine: boolean,
  title: string
): Promise<UploadResponse> {
  const formData = new FormData();
  files.forEach((f) => formData.append("files", f));
  formData.append("mode", mode);
  formData.append("skip_refine", String(skipRefine));
  formData.append("title", title);

  const res = await fetch(`${API_URL}/api/upload`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Upload failed");
  }
  return res.json();
}

export async function startTranscription(jobId: string): Promise<void> {
  const res = await fetch(`${API_URL}/api/transcribe/${jobId}`, {
    method: "POST",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Failed to start transcription");
  }
}

export async function startRefinement(jobId: string): Promise<void> {
  const res = await fetch(`${API_URL}/api/refine/${jobId}`, {
    method: "POST",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Failed to start refinement");
  }
}

export async function getJobStatus(jobId: string): Promise<StatusResponse> {
  const res = await fetch(`${API_URL}/api/status/${jobId}`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Failed to get job status");
  }
  return res.json();
}

export async function triggerExport(jobId: string): Promise<ExportResponse> {
  const res = await fetch(`${API_URL}/api/export/${jobId}`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Export failed");
  }
  return res.json();
}

export function getDownloadUrl(jobId: string, format: "txt" | "docx" | "raw"): string {
  return `${API_URL}/api/download/${jobId}/${format}`;
}

export interface JobSummary {
  job_id: string;
  status: string;
  step: string;
  created_at: string;
  num_files: number;
  num_pages: number;
}

export async function listJobs(): Promise<JobSummary[]> {
  const res = await fetch(`${API_URL}/api/jobs`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Failed to list jobs");
  }
  return res.json();
}
