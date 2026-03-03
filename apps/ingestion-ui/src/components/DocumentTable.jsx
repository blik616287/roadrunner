import { useState } from 'react';
import { deleteDocument, deleteLightragDocs, downloadDocumentUrl } from '../api';
import { useWorkspace } from '../hooks/useWorkspaceContext';
import JobStatusBadge from './JobStatusBadge';

export default function DocumentTable({ documents, lightragDocs, onRefresh }) {
  const { workspace } = useWorkspace();
  const [deleting, setDeleting] = useState(null);

  // Build map of LightRAG docs keyed by file_path
  const lrByPath = new Map();
  if (lightragDocs) {
    for (const [, docs] of Object.entries(lightragDocs)) {
      for (const doc of docs) {
        const fp = doc.file_path || '';
        if (fp) lrByPath.set(fp, doc);
      }
    }
  }

  // Merge: for each orchestrator doc, find matching LightRAG doc
  const matchedLrPaths = new Set();
  const merged = documents.map((d) => {
    const fileName = d.file_name || d.job_type || '-';
    // Match by file_name against LightRAG file_path
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
    return { ...d, fileName, lrDoc };
  });

  // LightRAG-only docs (not tracked by orchestrator)
  const orphaned = [];
  for (const [fp, doc] of lrByPath) {
    if (!matchedLrPaths.has(fp)) orphaned.push(doc);
  }

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

  if (!merged.length && !orphaned.length) {
    return <p className="text-gray-400 text-sm py-4">No documents found.</p>;
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b text-left text-gray-500">
            <th className="py-2 pr-3 font-medium">File</th>
            <th className="py-2 pr-3 font-medium">Ingestion</th>
            <th className="py-2 pr-3 font-medium">Graph</th>
            <th className="py-2 pr-3 font-medium">Created</th>
            <th className="py-2 pr-3 font-medium">Actions</th>
          </tr>
        </thead>
        <tbody>
          {merged.map((d) => (
            <tr key={d.job_id} className="border-b border-gray-100 hover:bg-gray-50">
              <td className="py-2 pr-3 max-w-[300px] truncate" title={d.fileName}>{d.fileName}</td>
              <td className="py-2 pr-3"><JobStatusBadge status={d.status} /></td>
              <td className="py-2 pr-3">
                {d.lrDoc ? (
                  <span className={`text-xs px-1.5 py-0.5 rounded ${
                    d.lrDoc.status === 'processed' ? 'bg-green-100 text-green-700' :
                    d.lrDoc.status === 'processing' ? 'bg-blue-100 text-blue-700' :
                    'bg-gray-100 text-gray-600'
                  }`}>{d.lrDoc.status}</span>
                ) : (
                  <span className="text-xs text-gray-400">-</span>
                )}
              </td>
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
          {orphaned.map((doc) => (
            <tr key={doc.id} className="border-b border-gray-100 hover:bg-gray-50 bg-yellow-50">
              <td className="py-2 pr-3 max-w-[300px] truncate" title={doc.file_path}>
                {doc.file_path || doc.id}
                <span className="ml-1 text-xs text-yellow-600">(graph only)</span>
              </td>
              <td className="py-2 pr-3"><span className="text-xs text-gray-400">-</span></td>
              <td className="py-2 pr-3">
                <span className={`text-xs px-1.5 py-0.5 rounded ${
                  doc.status === 'processed' ? 'bg-green-100 text-green-700' :
                  doc.status === 'processing' ? 'bg-blue-100 text-blue-700' :
                  'bg-gray-100 text-gray-600'
                }`}>{doc.status}</span>
              </td>
              <td className="py-2 pr-3 text-xs">
                {doc.created_at ? new Date(doc.created_at).toLocaleString() : '-'}
              </td>
              <td className="py-2 pr-3">
                <button
                  onClick={() => handleDeleteLrDoc(doc.id)}
                  disabled={deleting === doc.id}
                  className="text-red-600 hover:underline text-xs disabled:opacity-50"
                >
                  {deleting === doc.id ? 'Deleting...' : 'Delete'}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
