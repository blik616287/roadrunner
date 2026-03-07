import { useRef, useCallback, useEffect, useState } from 'react';
import ForceGraph2D from 'react-force-graph-2d';

const TYPE_COLORS = {
  person: '#3b82f6',
  organization: '#10b981',
  location: '#f59e0b',
  event: '#ef4444',
  concept: '#8b5cf6',
  technology: '#06b6d4',
  function: '#14b8a6',
  class: '#6366f1',
  module: '#f97316',
  file: '#84cc16',
  unknown: '#9ca3af',
};

function getColor(type) {
  const key = (type || '').toLowerCase();
  return TYPE_COLORS[key] || TYPE_COLORS.unknown;
}

const ZOOM_STEP = 1.5;
const BASE_RADIUS = 5;
const MIN_RADIUS = 3;
const MAX_RADIUS = 20;
const BASE_LINK_WIDTH = 1.5;
const MAX_LINK_WIDTH = 16;
const LABEL_ZOOM_THRESHOLD = 1.5;
const COOLDOWN_MS = 5000;

export default function GraphViewer({ graphData, onNodeClick }) {
  const [balloon, setBalloon] = useState(false);
  const fgRef = useRef();
  const containerRef = useRef();
  const [dimensions, setDimensions] = useState({ width: 0, height: 600 });
  const zoomLevel = useRef(1);

  // Compute max weights for scaling
  const maxNodeWeight = balloon
    ? Math.max(1, ...graphData.nodes.map((n) => n.weight || 1))
    : 1;
  const maxLinkWeight = balloon
    ? Math.max(1, ...graphData.links.map((l) => l.weight || 1))
    : 1;

  const nodeCount = graphData.nodes.length;

  const zoomIn = () => {
    const fg = fgRef.current;
    if (fg) fg.zoom(fg.zoom() * ZOOM_STEP, 300);
  };
  const zoomOut = () => {
    const fg = fgRef.current;
    if (fg) fg.zoom(fg.zoom() / ZOOM_STEP, 300);
  };
  const zoomFit = () => {
    const fg = fgRef.current;
    if (fg) fg.zoomToFit(400, 40);
  };
  const reheat = () => {
    const fg = fgRef.current;
    if (fg) fg.d3ReheatSimulation();
  };

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const update = () => {
      const rect = el.getBoundingClientRect();
      if (rect.width > 0) {
        setDimensions({
          width: Math.floor(rect.width),
          height: Math.max(500, window.innerHeight - 280),
        });
      }
    };
    update();
    const obs = new ResizeObserver(update);
    obs.observe(el);
    return () => obs.disconnect();
  }, []);

  // Tune d3-force for better spacing
  useEffect(() => {
    const fg = fgRef.current;
    if (!fg || !graphData.nodes.length) return;

    const n = graphData.nodes.length;
    // Stronger repulsion for larger graphs
    const chargeStrength = n > 500 ? -400 : n > 100 ? -250 : -120;
    fg.d3Force('charge').strength(chargeStrength).distanceMax(n > 500 ? 500 : 300);
    // Longer links to spread things out
    fg.d3Force('link').distance(n > 500 ? 80 : n > 100 ? 60 : 40);
    // Reheat so new forces take effect
    fg.d3ReheatSimulation();

    setTimeout(() => fg.zoomToFit(400, 40), 1500);
  }, [graphData, dimensions]);

  const getRadius = useCallback((node) => {
    if (!balloon) return BASE_RADIUS;
    const w = node.weight || 1;
    const logMax = Math.log(maxNodeWeight + 1);
    const t = logMax > 0 ? Math.log(w + 1) / logMax : 0;
    return MIN_RADIUS + t * (MAX_RADIUS - MIN_RADIUS);
  }, [balloon, maxNodeWeight]);

  const paintNode = useCallback((node, ctx, globalScale) => {
    zoomLevel.current = globalScale;
    const r = getRadius(node);
    ctx.beginPath();
    ctx.arc(node.x, node.y, r, 0, 2 * Math.PI);
    ctx.fillStyle = getColor(node.type);
    ctx.fill();

    if (balloon && (node.weight || 0) > 1) {
      ctx.font = `${Math.max(2, r * 0.6)}px sans-serif`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillStyle = '#fff';
      ctx.fillText(String(node.weight), node.x, node.y);
    }

    // Only draw labels when zoomed in enough (expensive for large graphs)
    if (globalScale >= LABEL_ZOOM_THRESHOLD) {
      ctx.font = '3px sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      ctx.fillStyle = '#374151';
      ctx.fillText(node.label, node.x, node.y + r + 1);
    }
  }, [balloon, getRadius]);

  const getLinkWidth = useCallback((link) => {
    if (!balloon) return BASE_LINK_WIDTH;
    const w = link.weight || 1;
    const logMax = Math.log(maxLinkWeight + 1);
    const t = logMax > 0 ? Math.log(w + 1) / logMax : 0;
    return BASE_LINK_WIDTH + t * (MAX_LINK_WIDTH - BASE_LINK_WIDTH);
  }, [balloon, maxLinkWeight]);

  const hasData = graphData.nodes.length > 0;
  const ready = hasData && dimensions.width > 0;

  return (
    <div ref={containerRef} className="border rounded bg-white w-full">
      {!hasData && (
        <div className="text-gray-400 text-sm py-8 text-center">
          No graph data available for this workspace.
        </div>
      )}
      {ready && (
        <div className="relative">
        <div className="absolute top-2 left-2 z-10 flex flex-col gap-1">
          <button onClick={zoomIn} className="w-8 h-8 bg-white border rounded shadow text-lg leading-none hover:bg-gray-50" title="Zoom in">+</button>
          <button onClick={zoomOut} className="w-8 h-8 bg-white border rounded shadow text-lg leading-none hover:bg-gray-50" title="Zoom out">&minus;</button>
          <button onClick={zoomFit} className="w-8 h-8 bg-white border rounded shadow text-xs leading-none hover:bg-gray-50" title="Fit to screen">Fit</button>
          <button onClick={reheat} className="w-8 h-8 bg-white border rounded shadow text-xs leading-none hover:bg-gray-50" title="Re-run layout">Re</button>
          <button onClick={() => setBalloon(b => !b)} className={`w-8 h-8 border rounded shadow text-xs leading-none ${balloon ? 'bg-blue-600 text-white border-blue-600' : 'bg-white hover:bg-gray-50'}`} title="Toggle weight sizing">Wght</button>
        </div>
        <div className="absolute top-2 right-2 z-10 text-xs text-gray-400 bg-white/80 px-2 py-1 rounded">
          {nodeCount} nodes
        </div>
        <ForceGraph2D
          ref={fgRef}
          graphData={graphData}
          nodeCanvasObject={paintNode}
          nodePointerAreaPaint={(node, color, ctx) => {
            const r = getRadius(node);
            ctx.beginPath();
            ctx.arc(node.x, node.y, r, 0, 2 * Math.PI);
            ctx.fillStyle = color;
            ctx.fill();
          }}
          linkColor={() => '#d1d5db'}
          linkWidth={getLinkWidth}
          linkDirectionalArrowLength={3}
          linkDirectionalArrowRelPos={1}
          onNodeClick={onNodeClick}
          width={dimensions.width}
          height={dimensions.height}
          cooldownTime={COOLDOWN_MS}
          warmupTicks={nodeCount > 500 ? 100 : 0}
          enableNodeDrag={true}
          d3AlphaDecay={nodeCount > 300 ? 0.05 : 0.0228}
          d3VelocityDecay={nodeCount > 300 ? 0.5 : 0.4}
        />
        </div>
      )}
      <div className="flex flex-wrap gap-2 p-2 border-t text-xs">
        {Object.entries(TYPE_COLORS).filter(([k]) => k !== 'unknown').map(([type, color]) => (
          <span key={type} className="flex items-center gap-1">
            <span className="w-2.5 h-2.5 rounded-full inline-block" style={{ backgroundColor: color }} />
            {type}
          </span>
        ))}
      </div>
    </div>
  );
}
