// src/dashboard/App.tsx
import React from 'react';
import DashboardLayout from './components/DashboardLayout';
import SessionList from './components/SessionList';
import OnboardingWizard from './onboarding/OnboardingWizard';
import PluginRegistry from './plugins/PluginRegistry';

export default function App() {
  // Simple route simulation for demo
  const [route, setRoute] = React.useState('dashboard');
  return (
    <DashboardLayout>
      <nav className="mb-4 flex gap-4">
        <button onClick={() => setRoute('dashboard')}>Dashboard</button>
        <button onClick={() => setRoute('onboarding')}>Onboarding</button>
        <button onClick={() => setRoute('plugins')}>Plugins</button>
      </nav>
      {route === 'dashboard' && <SessionList />}
      {route === 'onboarding' && <OnboardingWizard />}
      {route === 'plugins' && <PluginRegistry />}
    </DashboardLayout>
  );
}
