import { useState } from 'react';
import { useWorkspace } from '../hooks/useWorkspaceContext';
import { useJobs } from '../hooks/useJobs';
import { retryFailedJobs, retryJob } from '../api';
import JobTable from '../components/JobTable';

const FILTERS = [
  { label: 'All', value: null },
  { label: 'Queued', value: 'queued' },
  { label: 'Processing', value: 'processing' },
  { label: 'Indexing', value: 'indexing' },
  { label: 'Completed', value: 'completed' },
  { label: 'Failed', value: 'failed' },
];

export default function JobsPage() {
  const { workspace } = useWorkspace();
  const [statusFilter, setStatusFilter] = useState(() => {
    const stored = localStorage.getItem('jobsStatusFilter');
    return stored ? JSON.parse(stored) : null;
  });

  const handleStatusFilter = (value) => {
    setStatusFilter(value);
    localStorage.setItem('jobsStatusFilter', JSON.stringify(value));
  };
  const { jobs, loading, refresh } = useJobs(workspace, statusFilter);
  const [retrying, setRetrying] = useState(false);

  const failedCount = jobs.filter((j) => j.status === 'failed').length;

  const handleRetryAll = async () => {
    if (!confirm(`Retry all ${failedCount} failed jobs in "${workspace}"?`)) return;
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

  const handleRetryOne = async (jobId) => {
    try {
      await retryJob(jobId);
      refresh();
    } catch (e) {
      alert(`Retry failed: ${e.message}`);
    }
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-2xl font-bold">Jobs</h1>
        {failedCount > 0 && (
          <button
            onClick={handleRetryAll}
            disabled={retrying}
            className="px-3 py-1.5 rounded text-sm bg-orange-600 text-white hover:bg-orange-700 disabled:opacity-50"
          >
            {retrying ? 'Retrying...' : `Retry ${failedCount} Failed`}
          </button>
        )}
      </div>

      <div className="flex gap-1 mb-4">
        {FILTERS.map((f) => (
          <button
            key={f.label}
            onClick={() => handleStatusFilter(f.value)}
            className={`px-3 py-1.5 rounded text-sm ${
              statusFilter === f.value
                ? 'bg-gray-900 text-white'
                : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {loading ? (
        <p className="text-gray-400 text-sm">Loading...</p>
      ) : (
        <JobTable jobs={jobs} onRetry={handleRetryOne} />
      )}
    </div>
  );
}
