"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { StatusResponse } from "@/lib/types";
import { getJobStatus, startRefinement } from "@/lib/api";

interface RefineStepProps {
  jobId: string;
  skipRefine: boolean;
  onComplete: (status: StatusResponse) => void;
}

export default function RefineStep({ jobId, skipRefine, onComplete }: RefineStepProps) {
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [error, setError] = useState("");
  const [started, setStarted] = useState(false);
  const pollingRef = useRef(false);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // setTimeout-based polling chain
  const poll = useCallback(() => {
    if (!pollingRef.current) return;

    getJobStatus(jobId)
      .then((s) => {
        setStatus(s);

        if (s.status === "completed" && s.step === "refine") {
          pollingRef.current = false;
          onComplete(s);
        } else if (s.status === "failed") {
          pollingRef.current = false;
          setError(s.error || "Refinement failed");
        } else if (pollingRef.current) {
          timeoutRef.current = setTimeout(poll, 2000);
        }
      })
      .catch(() => {
        if (pollingRef.current) {
          timeoutRef.current = setTimeout(poll, 3000);
        }
      });
  }, [jobId, onComplete]);

  useEffect(() => {
    return () => {
      pollingRef.current = false;
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
    };
  }, []);

  // Auto-start refinement
  const startRefine = useCallback(async () => {
    setStarted(true);
    setError("");
    try {
      await startRefinement(jobId);
    } catch (e) {
      // 409 = already in progress (e.g. duplicate request) — just poll
      const msg = e instanceof Error ? e.message : "";
      if (!msg.includes("already in progress")) {
        setError(msg || "Failed to start refinement");
        return;
      }
    }
    pollingRef.current = true;
    poll();
  }, [jobId, poll]);

  // Start automatically when mounted (useRef prevents double-fire)
  const initRef = useRef(false);
  useEffect(() => {
    if (!initRef.current) {
      initRef.current = true;
      startRefine();
    }
  }, [startRefine]);

  const progress = status?.progress ?? 0;

  return (
    <div className="bg-white rounded-lg shadow p-6">
      <div className="flex items-center gap-3 mb-4">
        <span className="flex items-center justify-center w-8 h-8 rounded-full bg-blue-600 text-white text-sm font-bold">
          3
        </span>
        <h2 className="text-lg font-semibold text-gray-900">
          {skipRefine ? "Assembling" : "Refining"} Transcript
        </h2>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded">
          <p className="text-sm text-red-700">{error}</p>
          <button
            onClick={() => {
              setError("");
              setStarted(false);
            }}
            className="mt-2 text-sm text-red-600 underline hover:text-red-800"
          >
            Try again
          </button>
        </div>
      )}

      {!error && (
        <div className="space-y-4">
          <p className="text-sm text-gray-600">
            {skipRefine
              ? "Assembling raw transcription text..."
              : "Using Claude to fix OCR errors, restore paragraph structure, and clean up the transcript..."}
          </p>

          {/* Progress bar */}
          <div>
            <div className="flex justify-between text-sm text-gray-600 mb-1">
              <span>
                {skipRefine ? "Assembling..." : "Refining chunks..."}
              </span>
              <span>{Math.round(progress * 100)}%</span>
            </div>
            <div className="w-full bg-gray-200 rounded-full h-2.5">
              <div
                className="bg-purple-600 h-2.5 rounded-full transition-all duration-300"
                style={{ width: `${Math.max(progress * 100, 2)}%` }}
              />
            </div>
          </div>

          {progress < 1 && (
            <div className="flex items-center justify-center gap-2 text-xs text-gray-400">
              <span className="w-3 h-3 border-2 border-gray-300 border-t-transparent rounded-full animate-spin" />
              {skipRefine ? "Processing..." : "Claude is refining your transcript..."}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
