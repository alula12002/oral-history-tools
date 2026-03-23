"use client";

import { useCallback, useRef, useState } from "react";
import { ScanMode, UploadResponse } from "@/lib/types";
import { uploadFiles } from "@/lib/api";

const ACCEPTED_EXTENSIONS = [".jpg", ".jpeg", ".png", ".tiff", ".tif", ".pdf"];
const ACCEPT_STRING = ACCEPTED_EXTENSIONS.join(",");

interface UploadStepProps {
  onUploadComplete: (data: UploadResponse) => void;
  onOptionsChange?: (opts: { skipRefine: boolean }) => void;
}

export default function UploadStep({ onUploadComplete, onOptionsChange }: UploadStepProps) {
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);

  // Options
  const [mode, setMode] = useState<ScanMode>("handwritten");
  const [skipRefine, setSkipRefine] = useState(false);
  const [title, setTitle] = useState("");

  const inputRef = useRef<HTMLInputElement>(null);

  const validateFiles = useCallback((files: File[]) => {
    for (const f of files) {
      const ext = "." + f.name.split(".").pop()?.toLowerCase();
      if (!ACCEPTED_EXTENSIONS.includes(ext)) {
        return `Unsupported file: ${f.name}. Accepted: ${ACCEPTED_EXTENSIONS.join(", ")}`;
      }
    }
    return null;
  }, []);

  const handleFiles = useCallback(
    (files: File[]) => {
      const err = validateFiles(files);
      if (err) {
        setError(err);
        return;
      }
      setError("");
      setSelectedFiles(files);
    },
    [validateFiles]
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      const files = Array.from(e.dataTransfer.files);
      if (files.length > 0) handleFiles(files);
    },
    [handleFiles]
  );

  const handleSubmit = useCallback(async () => {
    if (selectedFiles.length === 0) return;
    setUploading(true);
    setError("");
    try {
      const result = await uploadFiles(selectedFiles, mode, skipRefine, title);
      onUploadComplete(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }, [selectedFiles, mode, skipRefine, title, onUploadComplete]);

  return (
    <div className="bg-white rounded-lg shadow p-6">
      <div className="flex items-center gap-3 mb-4">
        <span className="flex items-center justify-center w-8 h-8 rounded-full bg-blue-600 text-white text-sm font-bold">
          1
        </span>
        <h2 className="text-lg font-semibold text-gray-900">Upload Documents</h2>
      </div>

      {/* Drop zone */}
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        onClick={() => inputRef.current?.click()}
        className={`border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors ${
          dragging
            ? "border-blue-500 bg-blue-50"
            : "border-gray-300 hover:border-gray-400"
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={ACCEPT_STRING}
          onChange={(e) => {
            const files = Array.from(e.target.files || []);
            if (files.length > 0) handleFiles(files);
          }}
          className="hidden"
        />
        <p className="text-gray-600 mb-1">
          Drag & drop files here, or click to browse
        </p>
        <p className="text-sm text-gray-400">
          Accepts: JPG, PNG, PDF, TIFF
        </p>
      </div>

      {/* Selected files list */}
      {selectedFiles.length > 0 && (
        <div className="mt-4 space-y-1">
          <p className="text-sm font-medium text-gray-700">
            {selectedFiles.length} file{selectedFiles.length !== 1 ? "s" : ""} selected:
          </p>
          {selectedFiles.map((f, i) => (
            <p key={i} className="text-sm text-gray-500 pl-2">
              {f.name}{" "}
              <span className="text-gray-400">
                ({(f.size / 1024).toFixed(0)} KB)
              </span>
            </p>
          ))}
        </div>
      )}

      {/* Options panel */}
      {selectedFiles.length > 0 && (
        <div className="mt-6 border-t pt-4 space-y-4">
          <h3 className="text-sm font-semibold text-gray-700">Options</h3>

          {/* Mode selector */}
          <div>
            <label className="block text-sm text-gray-600 mb-1">
              Document type
            </label>
            <div className="flex gap-4">
              {(["handwritten", "printed", "mixed"] as ScanMode[]).map((m) => (
                <label key={m} className="flex items-center gap-1.5 text-sm">
                  <input
                    type="radio"
                    name="mode"
                    value={m}
                    checked={mode === m}
                    onChange={() => setMode(m)}
                    className="text-blue-600"
                  />
                  <span className="capitalize text-gray-700">{m}</span>
                </label>
              ))}
            </div>
          </div>

          {/* Title input */}
          <div>
            <label className="block text-sm text-gray-600 mb-1">
              Document title (optional)
            </label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. Family History Letters"
              className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </div>

          {/* Skip refine toggle */}
          <label className="flex items-center gap-2 text-sm text-gray-600">
            <input
              type="checkbox"
              checked={skipRefine}
              onChange={(e) => {
                setSkipRefine(e.target.checked);
                onOptionsChange?.({ skipRefine: e.target.checked });
              }}
              className="text-blue-600"
            />
            Skip refinement (raw OCR only)
          </label>
        </div>
      )}

      {error && <p className="mt-3 text-sm text-red-600">{error}</p>}

      {/* Upload button */}
      {selectedFiles.length > 0 && (
        <button
          onClick={handleSubmit}
          disabled={uploading}
          className="mt-4 w-full bg-blue-600 text-white py-2 px-4 rounded font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {uploading ? (
            <span className="flex items-center justify-center gap-2">
              <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
              Uploading...
            </span>
          ) : (
            `Upload ${selectedFiles.length} file${selectedFiles.length !== 1 ? "s" : ""}`
          )}
        </button>
      )}
    </div>
  );
}
