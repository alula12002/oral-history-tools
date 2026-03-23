"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { listJobs, JobSummary } from "@/lib/api";

const STATUS_COLORS: Record<string, string> = {
  completed: "bg-green-100 text-green-800",
  processing: "bg-blue-100 text-blue-800",
  pending: "bg-yellow-100 text-yellow-800",
  failed: "bg-red-100 text-red-800",
};

function formatDate(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export default function HistoryPage() {
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const fetchJobs = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await listJobs();
      setJobs(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load jobs");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchJobs();
  }, [fetchJobs]);

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-200">
        <div className="max-w-3xl mx-auto px-4 py-4 flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold text-gray-900">Job History</h1>
            <p className="text-sm text-gray-500">Previous transcription jobs</p>
          </div>
          <Link
            href="/"
            className="text-sm text-blue-600 hover:text-blue-800 font-medium"
          >
            New Transcription
          </Link>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-4 py-6">
        {error && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded">
            <p className="text-sm text-red-700">{error}</p>
            <button
              onClick={fetchJobs}
              className="mt-2 text-sm text-red-600 underline hover:text-red-800"
            >
              Retry
            </button>
          </div>
        )}

        {loading && (
          <div className="text-center py-12">
            <span className="inline-block w-6 h-6 border-2 border-gray-300 border-t-blue-600 rounded-full animate-spin" />
            <p className="mt-2 text-sm text-gray-500">Loading jobs...</p>
          </div>
        )}

        {!loading && !error && jobs.length === 0 && (
          <div className="text-center py-12 bg-white rounded-lg shadow">
            <p className="text-gray-500 mb-2">No transcription jobs yet</p>
            <Link
              href="/"
              className="text-sm text-blue-600 hover:text-blue-800 font-medium"
            >
              Start your first transcription
            </Link>
          </div>
        )}

        {!loading && jobs.length > 0 && (
          <div className="bg-white rounded-lg shadow divide-y">
            {jobs.map((job) => (
              <div
                key={job.job_id}
                className="px-4 py-3 flex items-center justify-between"
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-mono text-gray-700">
                      {job.job_id}
                    </span>
                    <span
                      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
                        STATUS_COLORS[job.status] || "bg-gray-100 text-gray-800"
                      }`}
                    >
                      {job.status}
                    </span>
                  </div>
                  <div className="flex gap-4 mt-1 text-xs text-gray-500">
                    <span>Step: {job.step || "—"}</span>
                    <span>
                      {job.num_files} file{job.num_files !== 1 ? "s" : ""}
                    </span>
                    {job.num_pages > 0 && (
                      <span>
                        {job.num_pages} page{job.num_pages !== 1 ? "s" : ""}
                      </span>
                    )}
                    <span>{formatDate(job.created_at)}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {!loading && jobs.length > 0 && (
          <div className="mt-4 text-center">
            <button
              onClick={fetchJobs}
              className="text-sm text-gray-500 hover:text-gray-700"
            >
              Refresh
            </button>
          </div>
        )}
      </main>
    </div>
  );
}
