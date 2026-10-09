use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentStatus {
    pub id: String,
    pub name: String,
    pub status: String,
    pub provider: String,
    pub model: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProviderStatus {
    pub id: String,
    pub name: String,
    pub enabled: bool,
    pub healthy: bool,
    pub latency_ms: Option<i32>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SystemStatus {
    pub version: String,
    pub uptime_seconds: i64,
    pub state: String,
    pub providers_online: i32,
    pub providers_total: i32,
    pub active_agents: i32,
    pub memory_used_mb: i64,
    pub cpu_percent: f64,
}
