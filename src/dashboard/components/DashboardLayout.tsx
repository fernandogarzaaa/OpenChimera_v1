// src/dashboard/components/DashboardLayout.tsx
import React from 'react';

// Dark shell: every panel (SessionList, AgentStatusPanel, LiveCanvas, ...) is
// styled with slate-800/900 surfaces and slate-300/400 text, which was near
// unreadable on the previous light gray-50 background.
export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen flex flex-col bg-slate-900 text-slate-100">
      <header className="bg-slate-950 border-b border-slate-800 text-white p-4 font-bold text-xl">
        OpenChimera Dashboard
      </header>
      <main className="flex-1 p-4 sm:p-6">{children}</main>
      <footer className="bg-slate-950 border-t border-slate-800 text-slate-400 text-center p-2 text-xs">
        &copy; 2026 OpenChimera
      </footer>
    </div>
  );
}
