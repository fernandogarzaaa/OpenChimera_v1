// src/dashboard/components/LiveCanvas.tsx
// Phase 3: Live Canvas — real-time visualization of agent activity,
// memory graph, and cognitive state.

import React, { useCallback, useEffect, useRef, useState } from 'react';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface CanvasNode {
  id: string;
  label: string;
  type: 'agent' | 'memory' | 'goal' | 'tool' | 'event';
  x: number;
  y: number;
  radius: number;
  color: string;
  active: boolean;
  meta?: Record<string, unknown>;
}

interface CanvasEdge {
  id: string;
  from: string;
  to: string;
  label?: string;
  strength: number; // 0-1
  type: 'dependency' | 'data_flow' | 'causal' | 'memory_link';
}

interface CanvasState {
  nodes: CanvasNode[];
  edges: CanvasEdge[];
  timestamp: number;
}

interface LiveCanvasProps {
  apiBase?: string;
  refreshIntervalMs?: number;
  width?: number;
  height?: number;
}

// ---------------------------------------------------------------------------
// Color map for node types
// ---------------------------------------------------------------------------

const NODE_COLORS: Record<string, string> = {
  agent: '#6366f1',    // indigo
  memory: '#10b981',   // emerald
  goal: '#f59e0b',     // amber
  tool: '#3b82f6',     // blue
  event: '#ef4444',    // red
};

// ---------------------------------------------------------------------------
// Mock data generator (used when API unavailable)
// ---------------------------------------------------------------------------

function generateMockState(): CanvasState {
  const now = Date.now();
  const nodes: CanvasNode[] = [
    { id: 'agent-1', label: 'Deliberation\nEngine', type: 'agent', x: 200, y: 150, radius: 40, color: NODE_COLORS.agent, active: true },
    { id: 'agent-2', label: 'Goal\nPlanner', type: 'agent', x: 400, y: 100, radius: 35, color: NODE_COLORS.agent, active: true },
    { id: 'agent-3', label: 'Memory\nSystem', type: 'memory', x: 150, y: 300, radius: 35, color: NODE_COLORS.memory, active: false },
    { id: 'agent-4', label: 'Tool\nExecutor', type: 'tool', x: 450, y: 280, radius: 30, color: NODE_COLORS.tool, active: true },
    { id: 'goal-1', label: 'Current\nGoal', type: 'goal', x: 320, y: 220, radius: 28, color: NODE_COLORS.goal, active: true },
    { id: 'event-1', label: 'User\nInput', type: 'event', x: 100, y: 180, radius: 22, color: NODE_COLORS.event, active: Math.random() > 0.5 },
  ];
  const edges: CanvasEdge[] = [
    { id: 'e1', from: 'event-1', to: 'agent-1', strength: 0.9, type: 'data_flow' },
    { id: 'e2', from: 'agent-1', to: 'goal-1', strength: 0.7, type: 'causal' },
    { id: 'e3', from: 'goal-1', to: 'agent-2', strength: 0.8, type: 'dependency' },
    { id: 'e4', from: 'agent-1', to: 'agent-3', strength: 0.6, type: 'memory_link' },
    { id: 'e5', from: 'agent-2', to: 'agent-4', strength: 0.75, type: 'data_flow' },
    { id: 'e6', from: 'agent-3', to: 'goal-1', strength: 0.5, type: 'memory_link' },
  ];
  return { nodes, edges, timestamp: now };
}

// ---------------------------------------------------------------------------
// Canvas rendering
// ---------------------------------------------------------------------------

function renderCanvas(
  ctx: CanvasRenderingContext2D,
  state: CanvasState,
  width: number,
  height: number,
  selectedNodeId: string | null,
  tick: number,
): void {
  ctx.clearRect(0, 0, width, height);

  // Background
  ctx.fillStyle = '#0f172a';
  ctx.fillRect(0, 0, width, height);

  // Grid
  ctx.strokeStyle = '#1e293b';
  ctx.lineWidth = 1;
  for (let x = 0; x < width; x += 40) {
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, height); ctx.stroke();
  }
  for (let y = 0; y < height; y += 40) {
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(width, y); ctx.stroke();
  }

  const nodeMap = new Map(state.nodes.map(n => [n.id, n]));

  // Draw edges
  for (const edge of state.edges) {
    const from = nodeMap.get(edge.from);
    const to = nodeMap.get(edge.to);
    if (!from || !to) continue;

    const edgeColors: Record<string, string> = {
      data_flow: '#38bdf8',
      causal: '#a78bfa',
      dependency: '#34d399',
      memory_link: '#fbbf24',
    };
    const color = edgeColors[edge.type] || '#64748b';
    ctx.strokeStyle = color;
    ctx.globalAlpha = 0.3 + edge.strength * 0.5;
    ctx.lineWidth = edge.strength * 3;

    // Animated dashes for active edges
    ctx.setLineDash([8, 4]);
    ctx.lineDashOffset = -(tick * 0.5);

    ctx.beginPath();
    ctx.moveTo(from.x, from.y);

    // Bezier curve
    const cpx = (from.x + to.x) / 2;
    const cpy = (from.y + to.y) / 2 - 30;
    ctx.quadraticCurveTo(cpx, cpy, to.x, to.y);
    ctx.stroke();

    ctx.setLineDash([]);
    ctx.globalAlpha = 1;

    // Arrow head
    const angle = Math.atan2(to.y - cpy, to.x - cpx);
    const headLen = 10;
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(to.x, to.y);
    ctx.lineTo(to.x - headLen * Math.cos(angle - 0.3), to.y - headLen * Math.sin(angle - 0.3));
    ctx.lineTo(to.x - headLen * Math.cos(angle + 0.3), to.y - headLen * Math.sin(angle + 0.3));
    ctx.closePath();
    ctx.fill();
  }

  // Draw nodes
  for (const node of state.nodes) {
    const isSelected = node.id === selectedNodeId;

    // Pulse animation for active nodes
    const pulse = node.active ? Math.sin(tick * 0.05) * 4 : 0;
    const r = node.radius + pulse;

    // Glow effect
    if (node.active) {
      const glow = ctx.createRadialGradient(node.x, node.y, r * 0.5, node.x, node.y, r * 2);
      glow.addColorStop(0, node.color + '40');
      glow.addColorStop(1, 'transparent');
      ctx.fillStyle = glow;
      ctx.beginPath();
      ctx.arc(node.x, node.y, r * 2, 0, Math.PI * 2);
      ctx.fill();
    }

    // Selection ring
    if (isSelected) {
      ctx.strokeStyle = '#ffffff';
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.arc(node.x, node.y, r + 6, 0, Math.PI * 2);
      ctx.stroke();
    }

    // Node circle
    ctx.fillStyle = node.color;
    ctx.globalAlpha = node.active ? 1 : 0.5;
    ctx.beginPath();
    ctx.arc(node.x, node.y, r, 0, Math.PI * 2);
    ctx.fill();
    ctx.globalAlpha = 1;

    // Node border
    ctx.strokeStyle = node.active ? '#ffffff' : '#475569';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.arc(node.x, node.y, r, 0, Math.PI * 2);
    ctx.stroke();

    // Label
    ctx.fillStyle = '#f8fafc';
    ctx.font = '10px monospace';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    const lines = node.label.split('\n');
    const lineHeight = 12;
    const yStart = node.y - (lines.length - 1) * lineHeight / 2;
    lines.forEach((line, i) => {
      ctx.fillText(line, node.x, yStart + i * lineHeight);
    });

    // Active indicator dot
    if (node.active) {
      ctx.fillStyle = '#22c55e';
      ctx.beginPath();
      ctx.arc(node.x + r * 0.7, node.y - r * 0.7, 5, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  // Timestamp
  ctx.fillStyle = '#475569';
  ctx.font = '11px monospace';
  ctx.textAlign = 'right';
  ctx.textBaseline = 'bottom';
  ctx.fillText(`t=${new Date(state.timestamp).toLocaleTimeString()}`, width - 8, height - 8);
}

// ---------------------------------------------------------------------------
// LiveCanvas Component
// ---------------------------------------------------------------------------

export default function LiveCanvas({ apiBase = '/api/v1', refreshIntervalMs = 2000, width = 600, height = 400 }: LiveCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [canvasState, setCanvasState] = useState<CanvasState>(generateMockState());
  const [selectedNode, setSelectedNode] = useState<CanvasNode | null>(null);
  const [isLive, setIsLive] = useState(false);
  const [tick, setTick] = useState(0);
  const animFrameRef = useRef<number>(0);
  const tickRef = useRef(0);

  // Fetch live state from API
  const fetchState = useCallback(async () => {
    try {
      const res = await fetch(`${apiBase}/canvas/state`);
      if (res.ok) {
        const data = await res.json();
        setCanvasState(data);
      }
    } catch {
      // API unavailable — use mock data with animation
      setCanvasState(prev => ({
        ...prev,
        timestamp: Date.now(),
        nodes: prev.nodes.map(n => ({ ...n, active: Math.random() > 0.3 })),
      }));
    }
  }, [apiBase]);

  // Animation loop
  useEffect(() => {
    const animate = () => {
      tickRef.current += 1;
      setTick(tickRef.current);
      animFrameRef.current = requestAnimationFrame(animate);
    };
    animFrameRef.current = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(animFrameRef.current);
  }, []);

  // Data refresh loop
  useEffect(() => {
    if (!isLive) return;
    const interval = setInterval(fetchState, refreshIntervalMs);
    return () => clearInterval(interval);
  }, [isLive, fetchState, refreshIntervalMs]);

  // Canvas render
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    renderCanvas(ctx, canvasState, width, height, selectedNode?.id ?? null, tick);
  }, [canvasState, selectedNode, tick, width, height]);

  // Node hit detection
  const handleCanvasClick = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    const hit = canvasState.nodes.find(n => {
      const dx = n.x - x;
      const dy = n.y - y;
      return Math.sqrt(dx * dx + dy * dy) <= n.radius + 5;
    });
    setSelectedNode(hit ?? null);
  }, [canvasState.nodes]);

  return (
    <div className="bg-slate-900 rounded-xl p-4 shadow-2xl border border-slate-700">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-white font-bold text-sm tracking-wide uppercase">⚡ Live Canvas</h2>
        <div className="flex gap-2 items-center">
          <button
            className={`text-xs px-3 py-1 rounded-full font-mono transition-colors ${
              isLive ? 'bg-green-500 text-black' : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
            }`}
            onClick={() => setIsLive(v => !v)}
          >
            {isLive ? '● LIVE' : '○ PAUSED'}
          </button>
          <button
            className="text-xs px-3 py-1 rounded-full bg-slate-700 text-slate-300 hover:bg-slate-600 font-mono"
            onClick={fetchState}
          >
            ↻ Refresh
          </button>
        </div>
      </div>

      <canvas
        ref={canvasRef}
        width={width}
        height={height}
        className="rounded-lg cursor-crosshair w-full"
        style={{ background: '#0f172a' }}
        onClick={handleCanvasClick}
      />

      {/* Node detail panel */}
      {selectedNode && (
        <div className="mt-3 p-3 bg-slate-800 rounded-lg border border-slate-600">
          <div className="flex items-center gap-2 mb-2">
            <div className="w-3 h-3 rounded-full" style={{ backgroundColor: selectedNode.color }} />
            <span className="text-white font-bold text-sm">{selectedNode.label.replace('\n', ' ')}</span>
            <span className={`text-xs px-2 py-0.5 rounded-full ${selectedNode.active ? 'bg-green-900 text-green-300' : 'bg-slate-700 text-slate-400'}`}>
              {selectedNode.active ? 'active' : 'idle'}
            </span>
          </div>
          <div className="text-slate-400 text-xs font-mono">
            <div>id: {selectedNode.id}</div>
            <div>type: {selectedNode.type}</div>
            <div>pos: ({Math.round(selectedNode.x)}, {Math.round(selectedNode.y)})</div>
          </div>
        </div>
      )}

      {/* Legend */}
      <div className="mt-3 flex flex-wrap gap-3">
        {Object.entries(NODE_COLORS).map(([type, color]) => (
          <div key={type} className="flex items-center gap-1.5">
            <div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: color }} />
            <span className="text-slate-400 text-xs font-mono">{type}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
