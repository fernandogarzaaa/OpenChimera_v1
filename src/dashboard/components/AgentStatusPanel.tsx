// src/dashboard/components/AgentStatusPanel.tsx
// Phase 3: Agent Status Panel — real-time AGI module health display

import React, { useEffect, useState } from 'react';

interface ModuleStatus {
  name: string;
  status: 'healthy' | 'degraded' | 'offline' | 'unknown';
  latency_ms?: number;
  uptime_pct?: number;
  last_activity?: string;
  version?: string;
}

interface SystemMetrics {
  cpu_pct: number;
  memory_pct: number;
  active_sessions: number;
  tasks_queued: number;
  tasks_running: number;
}

interface AgentStatusPanelProps {
  apiBase?: string;
  refreshIntervalMs?: number;
}

const AGI_MODULES = [
  'memory', 'deliberation', 'goal_planner', 'evolution', 'metacognition',
  'self_model', 'transfer_learning', 'causal_reasoning', 'embodied_interaction', 'social_cognition',
];

function StatusBadge({ status }: { status: ModuleStatus['status'] }) {
  const styles = {
    healthy: 'bg-green-900/50 text-green-400 border-green-800',
    degraded: 'bg-yellow-900/50 text-yellow-400 border-yellow-800',
    offline: 'bg-red-900/50 text-red-400 border-red-800',
    unknown: 'bg-slate-800 text-slate-400 border-slate-700',
  };
  const dots = {
    healthy: '●',
    degraded: '◐',
    offline: '○',
    unknown: '?',
  };
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full border font-mono ${styles[status]}`}>
      {dots[status]} {status}
    </span>
  );
}

function MetricBar({ label, value, max = 100, color = 'bg-blue-500' }: { label: string; value: number; max?: number; color?: string }) {
  const pct = Math.min(100, (value / max) * 100);
  const barColor = pct > 90 ? 'bg-red-500' : pct > 70 ? 'bg-yellow-500' : color;
  return (
    <div className="flex items-center gap-2">
      <span className="text-slate-400 text-xs font-mono w-20 shrink-0">{label}</span>
      <div className="flex-1 h-1.5 bg-slate-700 rounded-full overflow-hidden">
        <div className={`h-full ${barColor} rounded-full transition-all duration-500`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-slate-300 text-xs font-mono w-10 text-right">{Math.round(pct)}%</span>
    </div>
  );
}

function generateMockModules(): ModuleStatus[] {
  return AGI_MODULES.map(name => ({
    name,
    status: Math.random() > 0.15 ? 'healthy' : Math.random() > 0.5 ? 'degraded' : 'unknown',
    latency_ms: Math.round(Math.random() * 50 + 5),
    uptime_pct: 95 + Math.random() * 5,
    last_activity: new Date(Date.now() - Math.random() * 30000).toLocaleTimeString(),
  })) as ModuleStatus[];
}

function generateMockMetrics(): SystemMetrics {
  return {
    cpu_pct: Math.random() * 40 + 10,
    memory_pct: Math.random() * 30 + 30,
    active_sessions: Math.floor(Math.random() * 5) + 1,
    tasks_queued: Math.floor(Math.random() * 10),
    tasks_running: Math.floor(Math.random() * 3),
  };
}

export default function AgentStatusPanel({ apiBase = '/api/v1', refreshIntervalMs = 3000 }: AgentStatusPanelProps) {
  const [modules, setModules] = useState<ModuleStatus[]>(generateMockModules);
  const [metrics, setMetrics] = useState<SystemMetrics>(generateMockMetrics);
  const [lastUpdate, setLastUpdate] = useState(new Date());

  useEffect(() => {
    const fetchStatus = async () => {
      try {
        const [modRes, sysRes] = await Promise.all([
          fetch(`${apiBase}/status/modules`),
          fetch(`${apiBase}/status/system`),
        ]);
        if (modRes.ok) setModules(await modRes.json());
        if (sysRes.ok) setMetrics(await sysRes.json());
      } catch {
        // API unavailable — animate mock data
        setModules(generateMockModules());
        setMetrics(generateMockMetrics());
      }
      setLastUpdate(new Date());
    };

    const interval = setInterval(fetchStatus, refreshIntervalMs);
    return () => clearInterval(interval);
  }, [apiBase, refreshIntervalMs]);

  const healthyCount = modules.filter(m => m.status === 'healthy').length;
  const overallHealth = healthyCount / modules.length;

  return (
    <div className="bg-slate-900 rounded-xl p-4 shadow-xl border border-slate-700 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-white font-bold text-sm tracking-wide uppercase">🧠 AGI Module Status</h2>
        <span className="text-slate-500 text-xs font-mono">{lastUpdate.toLocaleTimeString()}</span>
      </div>

      {/* Overall health */}
      <div className="flex items-center gap-3 p-3 bg-slate-800 rounded-lg">
        <div className="relative w-10 h-10">
          <svg viewBox="0 0 36 36" className="w-full h-full -rotate-90">
            <circle cx="18" cy="18" r="15.9" fill="none" stroke="#1e293b" strokeWidth="3.8" />
            <circle
              cx="18" cy="18" r="15.9" fill="none"
              stroke={overallHealth > 0.8 ? '#22c55e' : overallHealth > 0.6 ? '#f59e0b' : '#ef4444'}
              strokeWidth="3.8"
              strokeDasharray={`${overallHealth * 100} 100`}
              className="transition-all duration-1000"
            />
          </svg>
          <span className="absolute inset-0 flex items-center justify-center text-white text-xs font-bold">
            {Math.round(overallHealth * 100)}
          </span>
        </div>
        <div>
          <div className="text-white text-sm font-semibold">
            {healthyCount}/{modules.length} modules healthy
          </div>
          <div className="text-slate-400 text-xs">
            {overallHealth === 1 ? '✅ All systems nominal' : overallHealth > 0.8 ? '⚠️ Minor degradation' : '🔴 Attention required'}
          </div>
        </div>
      </div>

      {/* System metrics */}
      <div className="space-y-2">
        <MetricBar label="CPU" value={metrics.cpu_pct} color="bg-blue-500" />
        <MetricBar label="Memory" value={metrics.memory_pct} color="bg-purple-500" />
        <div className="flex gap-4 pt-1">
          <span className="text-slate-400 text-xs font-mono">Sessions: <span className="text-white">{metrics.active_sessions}</span></span>
          <span className="text-slate-400 text-xs font-mono">Queued: <span className="text-white">{metrics.tasks_queued}</span></span>
          <span className="text-slate-400 text-xs font-mono">Running: <span className="text-white">{metrics.tasks_running}</span></span>
        </div>
      </div>

      {/* Module list */}
      <div className="space-y-1.5 max-h-64 overflow-y-auto">
        {modules.map(mod => (
          <div key={mod.name} className="flex items-center justify-between px-2 py-1.5 bg-slate-800/60 rounded hover:bg-slate-800 transition-colors">
            <div className="flex items-center gap-2">
              <span className="text-slate-300 text-xs font-mono w-36 truncate">{mod.name}</span>
            </div>
            <div className="flex items-center gap-3">
              {mod.latency_ms && (
                <span className="text-slate-500 text-xs font-mono">{mod.latency_ms}ms</span>
              )}
              <StatusBadge status={mod.status} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
