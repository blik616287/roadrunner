import { useState, useCallback, useEffect } from 'react';
import { queryGraph, getGraphLabels, getGraphByLabel, getWeights } from '../api';

export function useGraph(workspace) {
  const [graphData, setGraphData] = useState({ nodes: [], links: [] });
  const [weights, setWeights] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const buildGraph = useCallback((nodes, edges, weightData) => {
    const nodeMap = new Map();
    nodes.forEach((n) => {
      const id = n.id || n.entity_name || n.name;
      if (id && !nodeMap.has(id)) {
        const props = n.properties || {};
        const label = props.entity_id || id;
        nodeMap.set(id, {
          id,
          label,
          type: props.entity_type || n.entity_type || n.type || 'unknown',
          description: props.description || n.description || '',
          weight: weightData?.entities?.[label] || weightData?.entities?.[id] || 1,
        });
      }
    });

    const links = [];
    edges.forEach((e) => {
      const src = e.source || e.src_id;
      const tgt = e.target || e.tgt_id;
      if (src && tgt) {
        if (!nodeMap.has(src)) nodeMap.set(src, { id: src, label: src, type: 'unknown', weight: 1 });
        if (!nodeMap.has(tgt)) nodeMap.set(tgt, { id: tgt, label: tgt, type: 'unknown', weight: 1 });
        const props = e.properties || {};
        // Resolve node labels for weight lookup (Neo4j uses numeric IDs, weights use entity names)
        const srcLabel = nodeMap.get(src)?.label || src;
        const tgtLabel = nodeMap.get(tgt)?.label || tgt;
        const edgeKey = `${srcLabel}||${tgtLabel}`;
        const edgeKeyRev = `${tgtLabel}||${srcLabel}`;
        links.push({
          source: src,
          target: tgt,
          label: props.description || e.description || e.relation || e.type || '',
          weight: weightData?.relations?.[edgeKey] || weightData?.relations?.[edgeKeyRev] || 1,
        });
      }
    });

    return { nodes: Array.from(nodeMap.values()), links };
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
      const [labels, weightData] = await Promise.all([
        getGraphLabels(workspace),
        fetchWeights(),
      ]);
      setWeights(weightData);
      const allNodes = [];
      const allEdges = [];
      for (const label of labels) {
        const g = await getGraphByLabel(label, workspace);
        allNodes.push(...(g.nodes || []));
        allEdges.push(...(g.edges || []));
      }
      setGraphData(buildGraph(allNodes, allEdges, weightData));
    } catch (e) {
      setError(e.message);
      setGraphData({ nodes: [], links: [] });
    } finally {
      setLoading(false);
    }
  }, [workspace, buildGraph, fetchWeights]);

  const fetchGraph = useCallback(async (query, mode = 'local') => {
    if (!workspace) return;
    try {
      setLoading(true);
      setError(null);
      const [data, weightData] = await Promise.all([
        queryGraph(query, workspace, mode),
        fetchWeights(),
      ]);
      setWeights(weightData);
      const entities = data.data?.entities || data.entities || [];
      const relations = data.data?.relationships || data.data?.relations || data.relationships || data.relations || [];
      const nodes = entities.map((e) => ({
        id: e.entity_name || e.name,
        entity_name: e.entity_name || e.name,
        entity_type: e.entity_type || e.type,
        description: e.description,
      }));
      const edges = relations.map((r) => ({
        source: r.src_id || r.source,
        target: r.tgt_id || r.target,
        description: r.description || r.relation,
      }));
      setGraphData(buildGraph(nodes, edges, weightData));
    } catch (e) {
      setError(e.message);
      setGraphData({ nodes: [], links: [] });
    } finally {
      setLoading(false);
    }
  }, [workspace, buildGraph, fetchWeights]);

  useEffect(() => {
    fetchFullGraph();
  }, [fetchFullGraph]);

  return { graphData, weights, loading, error, fetchGraph, fetchFullGraph };
}
