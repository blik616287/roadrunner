import { useState, useMemo } from 'react';
import { useWorkspace } from '../hooks/useWorkspaceContext';
import { useJobs } from '../hooks/useJobs';
import {
  ingestDocument, ingestCodebase, retryJob, retryFailedJobs,
  prioritizeJob, deleteDocument, downloadDocumentUrl,
} from '../api';
import FileDropZone from '../components/FileDropZone';
import JobStatusBadge from '../components/JobStatusBadge';
import SortHeader from '../components/SortHeader';
import Pagination from '../components/Pagination';
import useSort from '../hooks/useSort';
import usePagination from '../hooks/usePagination';

const STATUS_FILTERS = [
  { label: 'All', value: null },
  { label: 'Queued', value: 'queued' },
  { label: 'Processing', value: 'processing' },
  { label: 'Completed', value: 'completed' },
  { label: 'Failed', value: 'failed' },
];

function formatDuration(start, end) {
  if (!start) return '-';
  const ms = (end ? new Date(end) : new Date()) - new Date(start);
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60000).toFixed(1)}m`;
}

function durationMs(start, end) {
  if (!start) return 0;
  return (end ? new Date(end) : new Date()) - new Date(start);
}

function shortId(id) {
  return id?.slice(0, 8) || '-';
}

function formatTime(iso) {
  if (!iso) return '-';
  return new Date(iso).toLocaleString();
}

export default function DataPage() {
  const { workspace } = useWorkspace();
  const [statusFilter, setStatusFilter] = useState(() => {
    const stored = localStorage.getItem('jobsStatusFilter');
    return stored ? JSON.parse(stored) : null;
  });
  const { jobs, loading, refresh } = useJobs(workspace, null);
  const [uploading, setUploading] = useState(false);
  const [message, setMessage] = useState(null);
  const [retrying, setRetrying] = useState(false);
  const [deleting, setDeleting] = useState(null);
  const [expanded, setExpanded] = useState(null);

  const handleStatusFilter = (value) => {
    setStatusFilter(value);
    localStorage.setItem('jobsStatusFilter', JSON.stringify(value));
  };

  const handleUpload = async (file, type, path) => {
    try {
      setUploading(true);
      setMessage(null);
      const result = type === 'codebase'
        ? await ingestCodebase(file, workspace)
        : await ingestDocument(file, workspace, path);
      setMessage({ type: 'success', text: `Queued: ${path || file.name} (job ${result.job_id?.slice(0, 8)})` });
      refresh();
    } catch (e) {
      setMessage({ type: 'error', text: `Upload failed: ${e.message}` });
    } finally {
      setUploading(false);
    }
  };

  const handleRetryAll = async () => {
    const count = rows.filter((r) => r.status === 'failed').length;
    if (!confirm(`Retry all ${count} failed jobs in "${workspace}"?`)) return;
    try {
      setRetrying(true);
      const result = await retryFailedJobs(workspace);
      alert(`Retried ${result.retried} jobs`);
      refresh();
    } catch (e) {
      alert(`Retry failed: ${e.message}`);
    } finally {
      setRetrying(false);
    }
  };

  const handleRetry = async (jobId) => {
    try {
      await retryJob(jobId);
      refresh();
    } catch (e) {
      alert(`Retry failed: ${e.message}`);
    }
  };

  const handlePrioritize = async (jobId) => {
    try {
      await prioritizeJob(jobId);
      setMessage({ type: 'success', text: `Job ${jobId.slice(0, 8)} prioritized` });
      refresh();
    } catch (e) {
      setMessage({ type: 'error', text: `Prioritize failed: ${e.message}` });
    }
  };

  const handleDelete = async (docId) => {
    if (!confirm('Delete this document and its knowledge graph data?')) return;
    try {
      setDeleting(docId);
      await deleteDocument(docId);
      refresh();
    } catch (e) {
      alert(`Delete failed: ${e.message}`);
    } finally {
      setDeleting(null);
    }
  };

  // Map orchestrator job status to display status
  const displayStatus = (status) => {
    if (status === 'indexing' || status === 'started' || status === 'processing') return 'processing';
    if (status === 'completed') return 'completed';
    if (status === 'failed') return 'failed';
    return 'queued';
  };

  // Single source of truth: orchestrator jobs only
  const rows = useMemo(() => {
    return jobs.map((j) => {
      const status = displayStatus(j.status);
      return {
        ...j,
        _file: j.file_name || j.job_type || '-',
        _status: status,
        _duration: status === 'completed'
          ? durationMs(j.started_at || j.created_at, j.completed_at)
          : status === 'processing' || status === 'failed'
          ? durationMs(j.started_at || j.created_at, j.completed_at || null)
          : 0,
      };
    });
  }, [jobs]);

  const failedCount = rows.filter((r) => r._status === 'failed').length;
  // Apply status button filter on merged _status (client-side)
  const statusFiltered = useMemo(
    () => statusFilter ? rows.filter((r) => r._status === statusFilter) : rows,
    [rows, statusFilter],
  );

  const { sorted, sortKey, sortDir, toggle } = useSort(statusFiltered, 'data', 'created_at', 'desc', '_file');
  const { paged, page, pageSize, totalPages, totalItems, setPage, changePageSize, PAGE_SIZE_OPTIONS } = usePagination(sorted, 'data');

  const thProps = { currentKey: sortKey, currentDir: sortDir, onToggle: toggle };

  return (
    <div>
      <FileDropZone onUpload={handleUpload} disabled={uploading} />

      {uploading && <p className="mt-3 text-sm text-blue-600">Uploading...</p>}
      {message && (
        <div className={`mt-3 p-3 rounded text-sm ${
          message.type === 'error' ? 'bg-red-50 text-red-700 border border-red-200' : 'bg-green-50 text-green-700 border border-green-200'
        }`}>
          {message.text}
        </div>
      )}

      <div className="flex items-center justify-between mt-6 mb-3">
        <div className="flex gap-1">
          {STATUS_FILTERS.map((f) => {
            const count = f.value ? rows.filter((r) => r._status === f.value).length : rows.length;
            return (
              <button
                key={f.label}
                onClick={() => handleStatusFilter(f.value)}
                className={`px-3 py-1.5 rounded text-sm ${
                  statusFilter === f.value
                    ? 'bg-gray-900 text-white'
                    : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                }`}
              >
                {f.label} <span className="opacity-60">({count})</span>
              </button>
            );
          })}
        </div>
        <div className="flex items-center gap-2">
          {failedCount > 0 && (
            <button
              onClick={handleRetryAll}
              disabled={retrying}
              className="px-3 py-1.5 rounded text-sm bg-orange-600 text-white hover:bg-orange-700 disabled:opacity-50"
            >
              {retrying ? 'Retrying...' : `Retry ${failedCount} Failed`}
            </button>
          )}
          <button onClick={refresh} className="text-sm text-blue-600 hover:underline">
            Refresh
          </button>
        </div>
      </div>

      {loading ? (
        <p className="text-gray-400 text-sm">Loading...</p>
      ) : !rows.length ? (
        <p className="text-gray-400 text-sm py-4">No documents found. Drop files above to get started.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm table-fixed">
            <colgroup>
              <col className="w-[45%]" />
              <col className="w-[10%]" />
              <col className="w-[18%]" />
              <col className="w-[10%]" />
              <col className="w-[17%]" />
            </colgroup>
            <thead>
              <tr className="border-b text-left text-gray-500">
                <SortHeader label="File" sortKey="_file" {...thProps} />
                <SortHeader label="Status" sortKey="_status" {...thProps} />
                <SortHeader label="Created" sortKey="created_at" {...thProps} />
                <SortHeader label="Duration" sortKey="_duration" {...thProps} />
                <th className="py-2 pr-3 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {paged.map((d) => (
                <>
                  <tr
                    key={d.job_id}
                    className="border-b border-gray-100 hover:bg-gray-50 cursor-pointer"
                    onClick={() => setExpanded(expanded === d.job_id ? null : d.job_id)}
                  >
                    <td className="py-2 pr-3 max-w-[350px] truncate" title={d._file}>
                      {d._file}
                    </td>
                    <td className="py-2 pr-3"><JobStatusBadge status={d._status} /></td>
                    <td className="py-2 pr-3 text-xs">{formatTime(d.created_at)}</td>
                    <td className="py-2 pr-3 text-xs">{
                      d._status === 'completed'
                        ? formatDuration(d.started_at || d.created_at, d.completed_at)
                        : d._status === 'processing'
                        ? formatDuration(d.started_at || d.created_at, null)
                        : d._status === 'failed'
                        ? formatDuration(d.started_at || d.created_at, d.completed_at || null)
                        : '-'
                    }</td>
                    <td className="py-2 pr-3 space-x-2">
                      {d.doc_id && (
                        <>
                          <a
                            href={downloadDocumentUrl(d.doc_id)}
                            className="text-blue-600 hover:underline text-xs"
                            target="_blank"
                            rel="noreferrer"
                            onClick={(e) => e.stopPropagation()}
                          >
                            Download
                          </a>
                          <button
                            onClick={(e) => { e.stopPropagation(); handleDelete(d.doc_id); }}
                            disabled={deleting === d.doc_id}
                            className="text-red-600 hover:underline text-xs disabled:opacity-50"
                          >
                            {deleting === d.doc_id ? 'Deleting...' : 'Delete'}
                          </button>
                        </>
                      )}
                      {d._status === 'queued' && (
                        <button
                          onClick={(e) => { e.stopPropagation(); handlePrioritize(d.job_id); }}
                          className="text-purple-600 hover:underline text-xs"
                        >
                          Prioritize
                        </button>
                      )}
                      {d._status === 'failed' && (
                        <button
                          onClick={(e) => { e.stopPropagation(); handleRetry(d.job_id); }}
                          className="text-orange-600 hover:underline text-xs"
                        >
                          Retry
                        </button>
                      )}
                    </td>
                  </tr>
                  {expanded === d.job_id && (
                    <tr key={`${d.job_id}-detail`} className="bg-gray-50">
                      <td colSpan={5} className="p-3">
                        <div className="text-xs space-y-1">
                          <p><span className="text-gray-500">Job ID:</span> {d.job_id}</p>
                          <p><span className="text-gray-500">Doc ID:</span> {d.doc_id}</p>
                          <p><span className="text-gray-500">Attempts:</span> {d.attempts}</p>
                          {d.error && (
                            <p className="text-red-600"><span className="text-gray-500">Error:</span> {d.error}</p>
                          )}
                          {d.result?.files?.length > 0 && (
                            <div>
                              <span className="text-gray-500">Files ({d.result.files.length}):</span>
                              <div className="mt-1 bg-white p-2 rounded border text-xs overflow-auto max-h-40 font-mono">
                                {d.result.files.map((f, i) => <div key={i}>{f}</div>)}
                              </div>
                            </div>
                          )}
                          {d.result && (
                            <div>
                              <span className="text-gray-500">Result:</span>
                              <pre className="mt-1 bg-white p-2 rounded border text-xs overflow-auto max-h-32">
                                {JSON.stringify(d.result, null, 2)}
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
          <Pagination
            page={page} totalPages={totalPages} totalItems={totalItems}
            pageSize={pageSize} onPageChange={setPage} onPageSizeChange={changePageSize}
            pageSizeOptions={PAGE_SIZE_OPTIONS}
          />
        </div>
      )}
    </div>
  );
}
