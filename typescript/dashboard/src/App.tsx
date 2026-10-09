import { useState, useEffect } from 'react'
import './App.css'

interface Status {
  version: string
  uptime_seconds: number
  state: string
  providers_online: number
  providers_total: number
  active_agents: number
  queued_tasks: number
  memory_used_mb: number
  cpu_percent: number
}

function App() {
  const [status, setStatus] = useState<Status | null>(null)
  const [tab, setTab] = useState<'dashboard' | 'providers' | 'cognitive'>('dashboard')

  useEffect(() => {
    const fetchStatus = async () => {
      try {
        const r = await fetch('http://127.0.0.1:7870/api/v2/status')
        const data = await r.json()
        setStatus(data)
      } catch {
        setStatus(null)
      }
    }
    fetchStatus()
    const id = setInterval(fetchStatus, 2000)
    return () => clearInterval(id)
  }, [])

  return (
    <div className="app">
      <header className="header">
        <h1>🐉 OpenChimera v2</h1>
        <nav>
          <button className={tab === 'dashboard' ? 'active' : ''} onClick={() => setTab('dashboard')}>Dashboard</button>
          <button className={tab === 'providers' ? 'active' : ''} onClick={() => setTab('providers')}>Providers</button>
          <button className={tab === 'cognitive' ? 'active' : ''} onClick={() => setTab('cognitive')}>Cognitive</button>
        </nav>
      </header>
      <main className="main">
        {tab === 'dashboard' && (
          <div className="dashboard">
            <div className="cards">
              <div className="card">
                <div className="card-title">Status</div>
                <div className={`card-value ${status?.state === 'online' ? 'good' : 'bad'}`}>{status?.state ?? 'unknown'}</div>
              </div>
              <div className="card">
                <div className="card-title">Providers</div>
                <div className="card-value">{status?.providers_online ?? 0} / {status?.providers_total ?? 0}</div>
              </div>
              <div className="card">
                <div className="card-title">Agents</div>
                <div className="card-value">{status?.active_agents ?? 0}</div>
              </div>
              <div className="card">
                <div className="card-title">CPU</div>
                <div className="card-value">{status?.cpu_percent?.toFixed(1) ?? 0}%</div>
              </div>
            </div>
            <div className="info">
              <p>Version: {status?.version ?? '...'}</p>
              <p>Uptime: {status ? Math.floor(status.uptime_seconds / 60) : 0} min</p>
              <p>Memory: {status?.memory_used_mb ?? 0} MB</p>
            </div>
          </div>
        )}
        {tab === 'providers' && (
          <div className="providers">
            <h2>Model Providers</h2>
            <p>Connect to the API to see live provider status.</p>
          </div>
        )}
        {tab === 'cognitive' && (
          <div className="cognitive">
            <h2>Cognitive Stack</h2>
            <div className="cog-grid">
              <div className="cog-card">
                <h3>AXIOM</h3>
                <p>Memory + Grounding</p>
              </div>
              <div className="cog-card">
                <h3>EVE</h3>
                <p>UX Validation</p>
              </div>
              <div className="cog-card">
                <h3>ADAM</h3>
                <p>Cognitive Substrate</p>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  )
}

export default App
