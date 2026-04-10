// src/dashboard/components/DashboardLayout.tsx
import React from 'react';

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen flex flex-col bg-gray-50">
      <header className="bg-blue-700 text-white p-4 font-bold text-xl">OpenChimera Dashboard</header>
      <main className="flex-1 p-6">{children}</main>
      <footer className="bg-gray-200 text-center p-2 text-xs">&copy; 2026 OpenChimera</footer>
    </div>
  );
}
