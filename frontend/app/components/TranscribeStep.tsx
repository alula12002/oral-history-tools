"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { StatusResponse } from "@/lib/types";
import { getJobStatus, startTranscription } from "@/lib/api";

interface TranscribeStepProps {
  jobId: string;
  onComplete: (status: StatusResponse) => void;
}

export default function TranscribeStep({ jobId, onComplete }: TranscribeStepProps) {
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [error, setError] = useState("");
  const [started, setStarted] = useState(false);
  const [starting, setStarting] = useState(false);
  const pollingRef = useRef(false);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // setTimeout-based polling chain (not setInterval)
  const poll = useCallback(() => {
    if (!pollingRef.current) return;

    getJobStatus(jobId)
      .then((s) => {
        setStatus(s);

        if (s.status === "completed" && s.step === "transcribe") {
          pollingRef.current = false;
          onComplete(s);
        } else if (s.status === "failed") {
          pollingRef.current = false;
          setError(s.error || "Transcription failed");
        } else if (pollingRef.current) {
          // Schedule next poll only after this one completes
          timeoutRef.current = setTimeout(poll, 1500);
        }
      })
      .catch((err) => {
        if (pollingRef.current) {
          timeoutRef.current = setTimeout(poll, 3000);
        }
      });
  }, [jobId, onComplete]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      pollingRef.current = false;
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
    };
  }, []);

  const handleStart = useCallback(async () => {
    setStarting(true);
    setError("");
    try {
      await startTranscription(jobId);
      setStarted(true);
      pollingRef.current = true;
      poll();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to start transcription");
    } finally {
      setStarting(false);
    }
  }, [jobId, poll]);

  const handleRetry = useCallback(() => {
    setError("");
    setStarted(false);
    setStatus(null);
  }, []);

  const progress = status?.progress ?? 0;
  const pagesCompleted = status?.page_results?.length ?? 0;
  const totalPages = status?.num_pages ?? 0;

  return (
    <div className="bg-white rounded-lg shadow p-6">
      <div className="flex items-center gap-3 mb-4">
        <span className="flex items-center justify-center w-8 h-8 rounded-full bg-blue-600 text-white text-sm font-bold">
          2
        </span>
        <h2 className="text-lg font-semibold text-gray-900">Transcribe</h2>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded">
          <p className="text-sm text-red-700">{error}</p>
          <button
            onClick={handleRetry}
            className="mt-2 text-sm text-red-600 underline hover:text-red-800"
          >
            Try again
          </button>
        </div>
      )}

      {!started && !error && (
        <div>
          <p className="text-sm text-gray-600 mb-4">
            Ready to transcribe your documents using Claude Vision API.
            Each page will be processed individually.
          </p>
          <button
            onClick={handleStart}
            disabled={starting}
            className="w-full bg-blue-600 text-white py-2 px-4 rounded font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {starting ? (
              <span className="flex items-center justify-center gap-2">
                <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                Starting...
              </span>
            ) : (
              "Start Transcription"
            )}
          </button>
        </div>
      )}

      {started && !error && (
        <div className="space-y-4">
          {/* Progress bar */}
          <div>
            <div className="flex justify-between text-sm text-gray-600 mb-1">
              <span>
                {totalPages > 0
                  ? `Page ${pagesCompleted} of ${totalPages}`
                  : "Preparing pages..."}
              </span>
              <span>{Math.round(progress * 100)}%</span>
            </div>
            <div className="w-full bg-gray-200 rounded-full h-2.5">
              <div
                className="bg-blue-600 h-2.5 rounded-full transition-all duration-300"
                style={{ width: `${Math.max(progress * 100, 2)}%` }}
              />
            </div>
          </div>

          {/* Per-page results as they come in */}
          {pagesCompleted > 0 && (
            <div className="border rounded divide-y max-h-64 overflow-y-auto">
              {status!.page_results.map((pr) => (
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
                  <span
                    className={
                      pr.status === "ok"
                        ? "text-green-600 font-medium"
                        : pr.status === "empty"
                        ? "text-yellow-600"
                        : "text-red-600"
                    }
                  >
                    {pr.status === "ok" && pr.confidence
                      ? `${pr.confidence} confidence`
                      : pr.status === "empty"
                      ? "Empty page"
                      : pr.status === "error"
                      ? "Error"
                      : "Processing..."}
                  </span>
                </div>
              ))}
            </div>
          )}

          {progress < 1 && (
            <p className="text-xs text-gray-400 text-center">
              Transcribing with Claude Vision API...
            </p>
          )}
        </div>
      )}
    </div>
  );
}
