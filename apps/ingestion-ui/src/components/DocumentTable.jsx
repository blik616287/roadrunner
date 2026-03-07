import { useState } from 'react';
import { deleteDocument, deleteLightragDocs, downloadDocumentUrl } from '../api';
import { useWorkspace } from '../hooks/useWorkspaceContext';
import useSort from '../hooks/useSort';
import usePagination from '../hooks/usePagination';
import JobStatusBadge from './JobStatusBadge';
import SortHeader from './SortHeader';
import Pagination from './Pagination';

export default function DocumentTable({ documents, lightragDocs, onRefresh }) {
  const { workspace } = useWorkspace();
  const [deleting, setDeleting] = useState(null);

  // Build map of LightRAG docs keyed by file_path
  const lrByPath = new Map();
  if (lightragDocs) {
    // Process in priority order: processed > processing > pending > failed
    // so the best status wins when multiple docs share a file_path
    const statusOrder = ['failed', 'pending', 'processing', 'processed'];
    for (const status of statusOrder) {
      for (const doc of (lightragDocs[status] || [])) {
        const fp = doc.file_path || '';
        if (fp) lrByPath.set(fp, doc);
      }
    }
  }

  // Derive a single merged status from ingestion + graph status.
  const mergedStatus = (ingestStatus, lrDoc) => {
    if (lrDoc) {
      if (lrDoc.status === 'processed') return 'completed';
      if (lrDoc.status === 'processing') return 'indexing';
      if (lrDoc.status === 'failed') return 'failed';
    }
    return ingestStatus;
  };

  // Merge: for each orchestrator doc, find matching LightRAG doc
  const matchedLrPaths = new Set();
  const merged = documents.map((d) => {
    const fileName = d.file_name || d.job_type || '-';
    let lrDoc = lrByPath.get(fileName);
    if (!lrDoc) {
      for (const [fp, doc] of lrByPath) {
        if (fp.endsWith(`/${fileName}`) || fileName.endsWith(`/${fp}`)) {
          lrDoc = doc;
          break;
        }
      }
    }
    if (lrDoc) matchedLrPaths.add(lrDoc.file_path);
    return { ...d, fileName, lrDoc, _status: mergedStatus(d.status, lrDoc) };
  });

  // LightRAG-only docs (not tracked by orchestrator)
  const orphaned = [];
  for (const [fp, doc] of lrByPath) {
    if (!matchedLrPaths.has(fp)) {
      orphaned.push({
        _id: doc.id,
        fileName: doc.file_path || doc.id,
        _status: doc.status === 'processed' ? 'completed' : doc.status,
        created_at: doc.created_at || '',
        _orphan: true,
        _lrDoc: doc,
      });
    }
  }

  const allRows = [...merged, ...orphaned];
  const { sorted, sortKey, sortDir, toggle } = useSort(allRows, 'documents', 'created_at', 'desc');
  const { paged, page, pageSize, totalPages, totalItems, setPage, changePageSize, PAGE_SIZE_OPTIONS } = usePagination(sorted, 'documents');

  const handleDelete = async (docId) => {
    if (!confirm('Delete this document and its knowledge graph data?')) return;
    try {
      setDeleting(docId);
      await deleteDocument(docId);
      onRefresh();
    } catch (e) {
      alert(`Delete failed: ${e.message}`);
    } finally {
      setDeleting(null);
    }
  };

  const handleDeleteLrDoc = async (lrDocId) => {
    if (!confirm('Delete this document from the knowledge graph?')) return;
    try {
      setDeleting(lrDocId);
      await deleteLightragDocs([lrDocId], workspace);
      onRefresh();
    } catch (e) {
      alert(`Delete failed: ${e.message}`);
    } finally {
      setDeleting(null);
    }
  };

  if (!allRows.length) {
    return <p className="text-gray-400 text-sm py-4">No documents found.</p>;
  }

  const thProps = { currentKey: sortKey, currentDir: sortDir, onToggle: toggle };

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b text-left text-gray-500">
            <SortHeader label="File" sortKey="fileName" {...thProps} />
            <SortHeader label="Status" sortKey="_status" {...thProps} />
            <SortHeader label="Created" sortKey="created_at" {...thProps} />
            <th className="py-2 pr-3 font-medium">Actions</th>
          </tr>
        </thead>
        <tbody>
          {paged.map((d) => d._orphan ? (
            <tr key={d._id} className="border-b border-gray-100 hover:bg-gray-50 bg-yellow-50">
              <td className="py-2 pr-3 max-w-[300px] truncate" title={d.fileName}>
                {d.fileName}
                <span className="ml-1 text-xs text-yellow-600">(graph only)</span>
              </td>
              <td className="py-2 pr-3"><JobStatusBadge status={d._status} /></td>
              <td className="py-2 pr-3 text-xs">
                {d.created_at ? new Date(d.created_at).toLocaleString() : '-'}
              </td>
              <td className="py-2 pr-3">
                <button
                  onClick={() => handleDeleteLrDoc(d._id)}
                  disabled={deleting === d._id}
                  className="text-red-600 hover:underline text-xs disabled:opacity-50"
                >
                  {deleting === d._id ? 'Deleting...' : 'Delete'}
                </button>
              </td>
            </tr>
          ) : (
            <tr key={d.job_id} className="border-b border-gray-100 hover:bg-gray-50">
              <td className="py-2 pr-3 max-w-[300px] truncate" title={d.fileName}>{d.fileName}</td>
              <td className="py-2 pr-3"><JobStatusBadge status={d._status} /></td>
              <td className="py-2 pr-3 text-xs">{new Date(d.created_at).toLocaleString()}</td>
              <td className="py-2 pr-3 space-x-2">
                <a
                  href={downloadDocumentUrl(d.doc_id)}
                  className="text-blue-600 hover:underline text-xs"
                  target="_blank"
                  rel="noreferrer"
                >
                  Download
                </a>
                <button
                  onClick={() => handleDelete(d.doc_id)}
                  disabled={deleting === d.doc_id}
                  className="text-red-600 hover:underline text-xs disabled:opacity-50"
                >
                  {deleting === d.doc_id ? 'Deleting...' : 'Delete'}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <Pagination
        page={page} totalPages={totalPages} totalItems={totalItems}
        pageSize={pageSize} onPageChange={setPage} onPageSizeChange={changePageSize}
        pageSizeOptions={PAGE_SIZE_OPTIONS}
      />
    </div>
  );
}
