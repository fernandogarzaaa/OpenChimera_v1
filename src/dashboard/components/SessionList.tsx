// src/dashboard/components/SessionList.tsx
import React, { useEffect, useState } from 'react';
import { getSessions, Session } from '../api/bridge';

export default function SessionList() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getSessions().then(res => {
      setLoading(res.loading);
      if (res.error) setError(res.error.message);
      else if (res.data) setSessions(res.data);
    });
  }, []);

  if (loading) return <div>Loading sessions...</div>;
  if (error) return <div className="text-red-600">Error: {error}</div>;
  return (
    <div>
      <h2 className="text-lg font-bold mb-2">Sessions</h2>
      <ul>
        {sessions.map(s => (
          <li key={s.id}>{s.user} ({s.active ? 'Active' : 'Inactive'})</li>
        ))}
      </ul>
    </div>
  );
}
