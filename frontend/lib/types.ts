export type JobStatus = "pending" | "processing" | "completed" | "failed";
export type ScanMode = "handwritten" | "printed" | "mixed";

export interface FileInfo {
  filename: string;
  size: number;
  type: "image" | "pdf";
}

export interface PageResult {
  sequence: number;
  source_file: string;
  source_page: number;
  text: string | null;
  confidence: string | null;
  status: string | null;
}

export interface UploadResponse {
  job_id: string;
  status: JobStatus;
  files: FileInfo[];
}

export interface StatusResponse {
  job_id: string;
  status: JobStatus;
  step: string;
  progress: number;
  error: string | null;
  num_pages: number;
  page_results: PageResult[];
  refined_text: string | null;
  export_paths: { txt: string; docx: string } | null;
}

export interface ExportResponse {
  job_id: string;
  txt: string;
  docx: string;
  raw?: string;
}
