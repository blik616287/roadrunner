import { useState, useCallback, useEffect } from 'react';
import { searchGraph, getTopGraph, getWeights } from '../api';

export function useGraph(workspace, limit = 2000) {
  const [graphData, setGraphData] = useState({ nodes: [], links: [] });
  const [weights, setWeights] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [truncated, setTruncated] = useState(false);
  const [totalCount, setTotalCount] = useState(0);
  const [totalNodes, setTotalNodes] = useState(0);
  const [totalEdges, setTotalEdges] = useState(0);

  const applyWeights = useCallback((nodes, edges, weightData) => {
    const finalNodes = nodes.map((n) => ({
      ...n,
      weight: weightData?.entities?.[n.label] || weightData?.entities?.[n.id] || 1,
    }));

    const nodeMap = new Map(finalNodes.map((n) => [n.id, n]));
    const finalLinks = edges.map((e) => {
      const srcLabel = nodeMap.get(e.source)?.label || e.source;
      const tgtLabel = nodeMap.get(e.target)?.label || e.target;
      const edgeKey = `${srcLabel}||${tgtLabel}`;
      const edgeKeyRev = `${tgtLabel}||${srcLabel}`;
      return {
        ...e,
        weight: weightData?.relations?.[edgeKey] || weightData?.relations?.[edgeKeyRev] || 1,
      };
    });

    return { nodes: finalNodes, links: finalLinks };
  }, []);

  const fetchWeights = useCallback(async () => {
    if (!workspace) return null;
    try {
      return await getWeights(workspace);
    } catch {
      return null;
    }
  }, [workspace]);

  const fetchFullGraph = useCallback(async () => {
    if (!workspace) return;
    try {
      setLoading(true);
      setError(null);
      const [data, weightData] = await Promise.all([
        getTopGraph(workspace, limit),
        fetchWeights(),
      ]);
      setWeights(weightData);
      const graph = applyWeights(data.nodes || [], data.edges || [], weightData);
      setGraphData(graph);
      setTruncated(data.truncated || false);
      setTotalCount(data.node_count || graph.nodes.length);
      setTotalNodes(data.total_nodes || 0);
      setTotalEdges(data.total_edges || 0);
    } catch (e) {
      setError(e.message);
      setGraphData({ nodes: [], links: [] });
    } finally {
      setLoading(false);
    }
  }, [workspace, limit, applyWeights, fetchWeights]);

  const fetchGraph = useCallback(async (query) => {
    if (!workspace) return;
    try {
      setLoading(true);
      setError(null);
      const [data, weightData] = await Promise.all([
        searchGraph(workspace, query),
        fetchWeights(),
      ]);
      setWeights(weightData);
      const graph = applyWeights(data.nodes || [], data.edges || [], weightData);
      setGraphData(graph);
      setTruncated(data.truncated || false);
      setTotalCount(data.node_count || graph.nodes.length);
    } catch (e) {
      setError(e.message);
      setGraphData({ nodes: [], links: [] });
    } finally {
      setLoading(false);
    }
  }, [workspace, applyWeights, fetchWeights]);

  useEffect(() => {
    fetchFullGraph();
  }, [fetchFullGraph]);

  return { graphData, weights, loading, error, truncated, totalCount, totalNodes, totalEdges, fetchGraph, fetchFullGraph };
}
