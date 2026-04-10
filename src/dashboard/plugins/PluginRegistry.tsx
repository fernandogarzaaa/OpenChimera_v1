// src/dashboard/plugins/PluginRegistry.tsx
import React from 'react';

const plugins = [
  { id: 'summarizer', name: 'Text Summarizer', version: '1.0.0', enabled: true },
  { id: 'web-search', name: 'Web Search', version: '1.0.0', enabled: false },
];

export default function PluginRegistry() {
  return (
    <div className="p-4">
      <h2 className="text-xl font-bold mb-2">Plugin Registry</h2>
      <table className="w-full border">
        <thead>
          <tr>
            <th>Name</th>
            <th>Version</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {plugins.map(p => (
            <tr key={p.id} className="border-t">
              <td>{p.name}</td>
              <td>{p.version}</td>
              <td>{p.enabled ? 'Enabled' : 'Disabled'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
