"use client";

import { useCallback, useState } from "react";
import Link from "next/link";
import { StatusResponse, UploadResponse } from "@/lib/types";
import UploadStep from "./components/UploadStep";
import TranscribeStep from "./components/TranscribeStep";
import RefineStep from "./components/RefineStep";
import ResultsStep from "./components/ResultsStep";

type PipelineStep = "upload" | "transcribe" | "refine" | "results";

export default function Home() {
  const [currentStep, setCurrentStep] = useState<PipelineStep>("upload");
  const [uploadData, setUploadData] = useState<UploadResponse | null>(null);
  const [skipRefine, setSkipRefine] = useState(false);
  const [lastStatus, setLastStatus] = useState<StatusResponse | null>(null);

  const handleUploadComplete = useCallback((data: UploadResponse & { skip_refine?: boolean }) => {
    setUploadData(data);
    setCurrentStep("transcribe");
  }, []);

  const handleTranscribeComplete = useCallback(
    (status: StatusResponse) => {
      setLastStatus(status);
      if (skipRefine) {
        // Still need to run refine endpoint (it handles skip_refine on backend)
        setCurrentStep("refine");
      } else {
        setCurrentStep("refine");
      }
    },
    [skipRefine]
  );

  const handleRefineComplete = useCallback((status: StatusResponse) => {
    setLastStatus(status);
    setCurrentStep("results");
  }, []);

  const handleReset = useCallback(() => {
    setCurrentStep("upload");
    setUploadData(null);
    setSkipRefine(false);
    setLastStatus(null);
  }, []);

  const jobId = uploadData?.job_id ?? "";

  // Step indicator
  const steps: { key: PipelineStep; label: string; num: number }[] = [
    { key: "upload", label: "Upload", num: 1 },
    { key: "transcribe", label: "Transcribe", num: 2 },
    { key: "refine", label: "Refine", num: 3 },
    { key: "results", label: "Results", num: 4 },
  ];

  const stepIndex = steps.findIndex((s) => s.key === currentStep);

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-200">
        <div className="max-w-3xl mx-auto px-4 py-4 flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold text-gray-900">
              Oral History Tools
            </h1>
            <p className="text-sm text-gray-500">
              Transcribe scanned documents using Claude Vision API
            </p>
          </div>
          <Link
            href="/history"
            className="text-sm text-blue-600 hover:text-blue-800 font-medium"
          >
            Job History
          </Link>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-4 py-6 space-y-6">
        {/* Step progress bar */}
        {currentStep !== "upload" && (
          <div className="flex items-center justify-between mb-2">
            {steps.map((s, i) => (
              <div key={s.key} className="flex items-center flex-1">
                <div className="flex items-center gap-2">
                  <span
                    className={`flex items-center justify-center w-7 h-7 rounded-full text-xs font-bold ${
                      i < stepIndex
                        ? "bg-green-600 text-white"
                        : i === stepIndex
                        ? "bg-blue-600 text-white"
                        : "bg-gray-200 text-gray-500"
                    }`}
                  >
                    {i < stepIndex ? "\u2713" : s.num}
                  </span>
                  <span
                    className={`text-sm hidden sm:inline ${
                      i <= stepIndex
                        ? "text-gray-900 font-medium"
                        : "text-gray-400"
                    }`}
                  >
                    {s.label}
                  </span>
                </div>
                {i < steps.length - 1 && (
                  <div
                    className={`flex-1 h-0.5 mx-3 ${
                      i < stepIndex ? "bg-green-600" : "bg-gray-200"
                    }`}
                  />
                )}
              </div>
            ))}
          </div>
        )}

        {/* Upload completed summary (shown during later steps) */}
        {currentStep !== "upload" && uploadData && (
          <div className="bg-white rounded-lg shadow p-4">
            <div className="flex items-center gap-3 mb-2">
              <span className="flex items-center justify-center w-8 h-8 rounded-full bg-green-600 text-white text-sm font-bold">
                &#10003;
              </span>
              <h2 className="text-lg font-semibold text-gray-900">
                Files Uploaded
              </h2>
            </div>
            <div className="flex flex-wrap gap-x-4 gap-y-1">
              {uploadData.files.map((f, i) => (
                <span key={i} className="text-sm text-gray-600">
                  {f.filename}{" "}
                  <span className="text-gray-400">
                    ({(f.size / 1024).toFixed(0)} KB)
                  </span>
                </span>
              ))}
            </div>
            <p className="text-xs text-gray-400 mt-1">Job: {jobId}</p>
          </div>
        )}

        {/* Current step component */}
        {currentStep === "upload" && (
          <UploadStep
            onUploadComplete={(data) => {
              // We need to know skipRefine for flow control;
              // it's not in UploadResponse, so we read it from UploadStep via a wrapper
              handleUploadComplete(data);
            }}
            onOptionsChange={(opts) => setSkipRefine(opts.skipRefine)}
          />
        )}

        {currentStep === "transcribe" && (
          <TranscribeStep
            jobId={jobId}
            onComplete={handleTranscribeComplete}
          />
        )}

        {currentStep === "refine" && (
          <RefineStep
            jobId={jobId}
            skipRefine={skipRefine}
            onComplete={handleRefineComplete}
          />
        )}

        {currentStep === "results" && lastStatus && (
          <ResultsStep jobId={jobId} status={lastStatus} />
        )}

        {/* Reset button */}
        {currentStep !== "upload" && (
          <div className="text-center">
            <button
              onClick={handleReset}
              className="text-sm text-gray-500 hover:text-gray-700"
            >
              Start over with new files
            </button>
          </div>
        )}
      </main>
    </div>
  );
}
