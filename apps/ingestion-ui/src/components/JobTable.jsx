import { useState } from 'react';
import JobStatusBadge from './JobStatusBadge';

function formatDuration(start, end) {
  if (!start) return '-';
  const s = new Date(start);
  const e = end ? new Date(end) : new Date();
  const ms = e - s;
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60000).toFixed(1)}m`;
}

function shortId(id) {
  return id?.slice(0, 8) || '-';
}

function formatTime(iso) {
  if (!iso) return '-';
  return new Date(iso).toLocaleString();
}

export default function JobTable({ jobs, onRetry }) {
  const [expanded, setExpanded] = useState(null);

  if (!jobs.length) {
    return <p className="text-gray-400 text-sm py-4">No jobs found.</p>;
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b text-left text-gray-500">
            <th className="py-2 pr-3 font-medium">Job</th>
            <th className="py-2 pr-3 font-medium">File</th>
            <th className="py-2 pr-3 font-medium">Status</th>
            <th className="py-2 pr-3 font-medium">Workspace</th>
            <th className="py-2 pr-3 font-medium">Created</th>
            <th className="py-2 pr-3 font-medium">Duration</th>
          </tr>
        </thead>
        <tbody>
          {jobs.map((j) => (
            <>
              <tr
                key={j.job_id}
                className="border-b border-gray-100 hover:bg-gray-50 cursor-pointer"
                onClick={() => setExpanded(expanded === j.job_id ? null : j.job_id)}
              >
                <td className="py-2 pr-3 font-mono text-xs">{shortId(j.job_id)}</td>
                <td className="py-2 pr-3 text-xs truncate max-w-[200px]" title={j.file_name}>{j.file_name || j.job_type}</td>
                <td className="py-2 pr-3"><JobStatusBadge status={j.status} /></td>
                <td className="py-2 pr-3">{j.workspace}</td>
                <td className="py-2 pr-3 text-xs">{formatTime(j.created_at)}</td>
                <td className="py-2 pr-3 text-xs">{formatDuration(j.started_at, j.completed_at)}</td>
              </tr>
              {expanded === j.job_id && (
                <tr key={`${j.job_id}-detail`} className="bg-gray-50">
                  <td colSpan={6} className="p-3">
                    <div className="text-xs space-y-1">
                      <p><span className="text-gray-500">Job ID:</span> {j.job_id}</p>
                      <p><span className="text-gray-500">Doc ID:</span> {j.doc_id}</p>
                      <p><span className="text-gray-500">Attempts:</span> {j.attempts}</p>
                      {j.error && (
                        <div className="flex items-start gap-2">
                          <p className="text-red-600"><span className="text-gray-500">Error:</span> {j.error}</p>
                          {onRetry && (
                            <button
                              onClick={(e) => { e.stopPropagation(); onRetry(j.job_id); }}
                              className="px-2 py-0.5 rounded text-xs bg-orange-600 text-white hover:bg-orange-700 shrink-0"
                            >
                              Retry
                            </button>
                          )}
                        </div>
                      )}
                      {j.result?.files?.length > 0 && (
                        <div>
                          <span className="text-gray-500">Files ({j.result.files.length}):</span>
                          <div className="mt-1 bg-white p-2 rounded border text-xs overflow-auto max-h-40 font-mono">
                            {j.result.files.map((f, i) => <div key={i}>{f}</div>)}
                          </div>
                        </div>
                      )}
                      {j.result && (
                        <div>
                          <span className="text-gray-500">Result:</span>
                          <pre className="mt-1 bg-white p-2 rounded border text-xs overflow-auto">
                            {JSON.stringify(j.result, null, 2)}
                          </pre>
                        </div>
                      )}
                    </div>
                  </td>
                </tr>
              )}
            </>
          ))}
        </tbody>
      </table>
    </div>
  );
}
