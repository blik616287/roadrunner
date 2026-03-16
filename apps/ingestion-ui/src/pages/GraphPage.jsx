import { useState } from 'react';
import { useWorkspace } from '../hooks/useWorkspaceContext';
import { useGraph } from '../hooks/useGraph';
import { reconcileGraph } from '../api';
import GraphViewer from '../components/GraphViewer';

export default function GraphPage() {
  const { workspace } = useWorkspace();
  const [nodeLimit, setNodeLimit] = useState(2000);
  const {
    graphData, loading, error, truncated, totalCount,
    totalNodes, totalEdges, fetchGraph, fetchFullGraph,
  } = useGraph(workspace, nodeLimit);
  const [query, setQuery] = useState('');
  const [selectedNode, setSelectedNode] = useState(null);
  const [reconciling, setReconciling] = useState(false);
  const [reconcileResult, setReconcileResult] = useState(null);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (query.trim()) fetchGraph(query.trim());
  };

  const handleReconcile = async () => {
    try {
      setReconciling(true);
      setReconcileResult(null);
      const result = await reconcileGraph(workspace);
      setReconcileResult(result);
      fetchFullGraph();
    } catch (err) {
      setReconcileResult({ error: err.message });
    } finally {
      setReconciling(false);
    }
  };

  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">Knowledge Graph</h1>

      <form onSubmit={handleSubmit} className="flex gap-2 mb-4">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search graph by query..."
          className="flex-1 border rounded px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
        />
        <button
          type="submit"
          disabled={loading || !query.trim()}
          className="bg-blue-600 text-white px-4 py-2 rounded text-sm hover:bg-blue-700 disabled:opacity-50"
        >
          {loading ? 'Loading...' : 'Search'}
        </button>
        <button
          type="button"
          onClick={() => { setQuery(''); fetchFullGraph(); }}
          disabled={loading}
          className="bg-gray-200 text-gray-700 px-4 py-2 rounded text-sm hover:bg-gray-300 disabled:opacity-50"
        >
          Show All
        </button>
        <button
          type="button"
          onClick={handleReconcile}
          disabled={reconciling || loading}
          className="bg-orange-600 text-white px-4 py-2 rounded text-sm hover:bg-orange-700 disabled:opacity-50"
        >
          {reconciling ? 'Reconciling...' : 'Reconcile'}
        </button>
      </form>

      <div className="flex items-center gap-3 mb-4">
        <label className="text-sm text-gray-500 whitespace-nowrap">Nodes: {nodeLimit.toLocaleString()}</label>
        <input
          type="range"
          min={50}
          max={2000}
          step={50}
          value={nodeLimit}
          onChange={(e) => setNodeLimit(Number(e.target.value))}
          className="flex-1 max-w-xs"
        />
        {totalNodes > 0 && (
          <span className="text-sm text-gray-500 ml-4">
            Total: {totalNodes.toLocaleString()} entities, {totalEdges.toLocaleString()} relations
          </span>
        )}
      </div>

      {reconcileResult && (
        <div className={`border rounded p-3 text-sm mb-4 ${reconcileResult.error ? 'bg-red-50 border-red-200 text-red-700' : 'bg-orange-50 border-orange-200 text-orange-800'}`}>
          {reconcileResult.error
            ? reconcileResult.error
            : `Created ${reconcileResult.bridges_created} bridge edges across ${reconcileResult.isolated_clusters || 0} isolated clusters (${reconcileResult.clusters_found} total components)`}
          <button onClick={() => setReconcileResult(null)} className="ml-3 text-xs text-gray-400 hover:text-gray-600">dismiss</button>
        </div>
      )}

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 rounded p-3 text-sm mb-4">{error}</div>
      )}

      {truncated && (
        <div className="bg-yellow-50 border border-yellow-200 text-yellow-800 rounded p-3 text-sm mb-4">
          Showing top {nodeLimit.toLocaleString()} entities by degree out of {totalCount.toLocaleString()} total. Use the slider or search to explore.
        </div>
      )}

      <div className="relative">
        <GraphViewer graphData={graphData} onNodeClick={(node) => setSelectedNode(node)} />
        {selectedNode && (
          <div className="absolute top-2 right-2 w-64 bg-white border rounded shadow-lg p-4 z-10">
            <h3 className="font-semibold text-sm mb-2">{selectedNode.label}</h3>
            <p className="text-xs text-gray-500 mb-1">Type: {selectedNode.type}</p>
            {selectedNode.weight > 1 && (
              <p className="text-xs text-gray-500 mb-1">Chunks: {selectedNode.weight}</p>
            )}
            {selectedNode.description && (
              <p className="text-xs text-gray-600 mt-2">{selectedNode.description}</p>
            )}
            <button
              onClick={() => setSelectedNode(null)}
              className="mt-3 text-xs text-gray-400 hover:text-gray-600"
            >
              Close
            </button>
          </div>
        )}
      </div>

      <p className="text-xs text-gray-400 mt-2">
        {graphData.nodes.length} entities, {graphData.links.length} relations
        {truncated && ` (of ${totalCount.toLocaleString()} total)`}
      </p>
    </div>
  );
}
