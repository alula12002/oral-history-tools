"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { StatusResponse } from "@/lib/types";
import { triggerExport, getDownloadUrl, retryFailedPages, getJobStatus } from "@/lib/api";

interface ResultsStepProps {
  jobId: string;
  status: StatusResponse;
}

const ERROR_LABELS: Record<string, string> = {
  rate_limit: "Rate limited",
  timeout: "Timed out",
  connection: "Connection error",
  server_error: "Server error",
  auth_error: "Auth error",
  image_rejected: "Image rejected",
  api_error: "API error",
  unknown: "Unknown error",
};

export default function ResultsStep({ jobId, status: initialStatus }: ResultsStepProps) {
  const [status, setStatus] = useState(initialStatus);
  const [exporting, setExporting] = useState(false);
  const [exported, setExported] = useState(false);
  const [error, setError] = useState("");
  const [showFullText, setShowFullText] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Clean up polling on unmount
  useEffect(() => {
    return () => {
      if (pollRef.current) clearTimeout(pollRef.current);
    };
  }, []);

  const handleExport = useCallback(async () => {
    setExporting(true);
    setError("");
    try {
      await triggerExport(jobId);
      setExported(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Export failed");
    } finally {
      setExporting(false);
    }
  }, [jobId]);

  const handleDownload = useCallback(
    (format: "txt" | "docx" | "raw") => {
      const url = getDownloadUrl(jobId, format);
      window.open(url, "_blank");
    },
    [jobId]
  );

  const handleRetry = useCallback(async () => {
    setRetrying(true);
    setError("");
    try {
      await retryFailedPages(jobId);
      // Poll until retry completes
      const poll = async () => {
        try {
          const updated = await getJobStatus(jobId);
          setStatus(updated);
          if (updated.status === "processing") {
            pollRef.current = setTimeout(poll, 2000);
          } else {
            setRetrying(false);
          }
        } catch {
          setRetrying(false);
          setError("Failed to check retry status");
        }
      };
      pollRef.current = setTimeout(poll, 2000);
    } catch (e) {
      setRetrying(false);
      setError(e instanceof Error ? e.message : "Retry failed");
    }
  }, [jobId]);

  const pageResults = status.page_results || [];
  const okPages = pageResults.filter((p) => p.status === "ok");
  const failedPages = pageResults.filter((p) => p.status === "error");
  const refinedText = status.refined_text || "";

  // Preview: first 500 chars
  const previewText = refinedText.length > 500 && !showFullText
    ? refinedText.slice(0, 500) + "..."
    : refinedText;

  return (
    <div className="bg-white rounded-lg shadow p-6">
      <div className="flex items-center gap-3 mb-4">
        <span className="flex items-center justify-center w-8 h-8 rounded-full bg-green-600 text-white text-sm font-bold">
          4
        </span>
        <h2 className="text-lg font-semibold text-gray-900">Results</h2>
      </div>

      {/* Summary stats */}
      <div className="grid grid-cols-3 gap-4 mb-6">
        <div className="text-center p-3 bg-gray-50 rounded">
          <div className="text-2xl font-bold text-gray-900">{okPages.length}</div>
          <div className="text-xs text-gray-500">Pages transcribed</div>
        </div>
        <div className="text-center p-3 bg-gray-50 rounded">
          <div className="text-2xl font-bold text-gray-900">
            {refinedText.split(/\s+/).filter(Boolean).length}
          </div>
          <div className="text-xs text-gray-500">Words</div>
        </div>
        <div className="text-center p-3 bg-gray-50 rounded">
          <div className="text-2xl font-bold text-gray-900">
            {okPages.length > 0
              ? Math.round(
                  okPages.reduce((sum, p) => {
                    const conf = parseInt(p.confidence || "0", 10);
                    return sum + (isNaN(conf) ? 0 : conf);
                  }, 0) / okPages.length
                )
              : 0}
            %
          </div>
          <div className="text-xs text-gray-500">Avg confidence</div>
        </div>
      </div>

      {/* Failed pages banner + retry */}
      {failedPages.length > 0 && (
        <div className="mb-4 p-3 bg-amber-50 border border-amber-200 rounded">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-amber-800">
                {failedPages.length} page{failedPages.length > 1 ? "s" : ""} failed
              </p>
              <p className="text-xs text-amber-600 mt-0.5">
                {failedPages.map((p) => `Page ${p.sequence}`).join(", ")}
              </p>
            </div>
            <button
              onClick={handleRetry}
              disabled={retrying}
              className="px-3 py-1.5 bg-amber-600 text-white text-sm rounded font-medium hover:bg-amber-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {retrying ? (
                <span className="flex items-center gap-1.5">
                  <span className="w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  Retrying...
                </span>
              ) : (
                "Retry failed pages"
              )}
            </button>
          </div>
        </div>
      )}

      {/* Per-page confidence breakdown */}
      <details className="mb-4">
        <summary className="text-sm font-medium text-gray-700 cursor-pointer hover:text-gray-900">
          Per-page confidence scores
        </summary>
        <div className="mt-2 border rounded divide-y max-h-48 overflow-y-auto">
          {pageResults.map((pr) => (
            <div
              key={pr.sequence}
              className="px-3 py-2 flex items-center justify-between text-sm"
            >
              <span className="text-gray-700">
                Page {pr.sequence}{" "}
                <span className="text-gray-400">
                  ({pr.source_file}
                  {pr.source_page > 1 ? `, p${pr.source_page}` : ""})
                </span>
              </span>
              <span className="flex items-center gap-2">
                {pr.status === "error" && pr.error_message && (
                  <span className="text-xs text-gray-400" title={pr.error_message}>
                    {ERROR_LABELS[pr.error_code || ""] || pr.error_code || ""}
                  </span>
                )}
                <span
                  className={
                    pr.status === "ok"
                      ? "text-green-600 font-medium"
                      : pr.status === "error"
                      ? "text-red-500 font-medium"
                      : "text-yellow-600"
                  }
                >
                  {pr.status === "error" ? "error" : pr.confidence || pr.status}
                </span>
              </span>
            </div>
          ))}
        </div>
      </details>

      {/* Transcript preview */}
      <div className="mb-4">
        <h3 className="text-sm font-medium text-gray-700 mb-2">
          Transcript Preview
        </h3>
        <div className="border rounded p-4 bg-gray-50 max-h-96 overflow-y-auto">
          <pre className="text-sm text-gray-800 whitespace-pre-wrap font-sans leading-relaxed">
            {previewText}
          </pre>
        </div>
        {refinedText.length > 500 && (
          <button
            onClick={() => setShowFullText(!showFullText)}
            className="mt-2 text-sm text-blue-600 hover:text-blue-800"
          >
            {showFullText ? "Show less" : "Show full transcript"}
          </button>
        )}
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded">
          <p className="text-sm text-red-700">{error}</p>
        </div>
      )}

      {/* Export and download */}
      {!exported ? (
        <button
          onClick={handleExport}
          disabled={exporting}
          className="w-full bg-green-600 text-white py-2 px-4 rounded font-medium hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {exporting ? (
            <span className="flex items-center justify-center gap-2">
              <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
              Generating files...
            </span>
          ) : (
            "Generate Download Files"
          )}
        </button>
      ) : (
        <div className="space-y-2">
          <div className="flex gap-3">
            <button
              onClick={() => handleDownload("txt")}
              className="flex-1 bg-gray-800 text-white py-2 px-4 rounded font-medium hover:bg-gray-900 transition-colors"
            >
              Download .txt
            </button>
            <button
              onClick={() => handleDownload("docx")}
              className="flex-1 bg-blue-600 text-white py-2 px-4 rounded font-medium hover:bg-blue-700 transition-colors"
            >
              Download .docx
            </button>
          </div>
          <button
            onClick={() => handleDownload("raw")}
            className="w-full bg-gray-100 text-gray-700 py-2 px-4 rounded font-medium hover:bg-gray-200 border border-gray-300 transition-colors text-sm"
          >
            Download Raw Transcript (before refinement)
          </button>
        </div>
      )}
    </div>
  );
}
