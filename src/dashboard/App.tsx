// src/dashboard/App.tsx
import React from 'react';
import DashboardLayout from './components/DashboardLayout';
import SessionList from './components/SessionList';
import LiveCanvas from './components/LiveCanvas';
import AgentStatusPanel from './components/AgentStatusPanel';
import VoiceInterface from './components/VoiceInterface';
import OnboardingWizard from './onboarding/OnboardingWizard';
import PluginRegistry from './plugins/PluginRegistry';

type Route = 'dashboard' | 'canvas' | 'voice' | 'onboarding' | 'plugins';

const NAV_ITEMS: Array<{ id: Route; label: string; icon: string }> = [
  { id: 'dashboard', label: 'Dashboard', icon: '📊' },
  { id: 'canvas', label: 'Live Canvas', icon: '⚡' },
  { id: 'voice', label: 'Voice', icon: '🎙️' },
  { id: 'onboarding', label: 'Onboarding', icon: '🚀' },
  { id: 'plugins', label: 'Plugins', icon: '🔌' },
];

export default function App() {
  const [route, setRoute] = React.useState<Route>('dashboard');

  return (
    <DashboardLayout>
      {/* Navigation */}
      <nav className="mb-6 flex gap-2 border-b border-slate-700 pb-3">
        {NAV_ITEMS.map(item => (
          <button
            key={item.id}
            onClick={() => setRoute(item.id)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
              route === item.id
                ? 'bg-indigo-600 text-white'
                : 'text-slate-400 hover:text-white hover:bg-slate-800'
            }`}
          >
            <span>{item.icon}</span>
            <span>{item.label}</span>
          </button>
        ))}
      </nav>

      {/* Route content */}
      {route === 'dashboard' && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <SessionList />
          <AgentStatusPanel />
        </div>
      )}
      {route === 'canvas' && (
        <div className="space-y-6">
          <LiveCanvas width={720} height={450} refreshIntervalMs={2000} />
        </div>
      )}
      {route === 'voice' && (
        <div className="max-w-lg mx-auto">
          <VoiceInterface />
        </div>
      )}
      {route === 'onboarding' && <OnboardingWizard />}
      {route === 'plugins' && <PluginRegistry />}
    </DashboardLayout>
  );
}
