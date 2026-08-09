use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SystemStatus {
    pub version: String,
    pub uptime_seconds: u64,
    pub state: RuntimeState,
    pub providers_online: usize,
    pub providers_total: usize,
    pub active_agents: usize,
    pub queued_tasks: usize,
    pub memory_used_mb: u64,
    pub cpu_percent: f32,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum RuntimeState {
    Initializing,
    Online,
    Degraded,
    Offline,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProviderStatus {
    pub id: String,
    pub name: String,
    pub enabled: bool,
    pub healthy: bool,
    pub latency_ms: Option<u64>,
    pub default_model: String,
    pub models: Vec<String>,
    pub last_error: Option<String>,
    pub last_checked: DateTime<Utc>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentTask {
    pub id: String,
    pub name: String,
    pub status: TaskStatus,
    pub provider: String,
    pub model: String,
    pub prompt_preview: String,
    pub created_at: DateTime<Utc>,
    pub completed_at: Option<DateTime<Utc>>,
    pub result_preview: Option<String>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum TaskStatus {
    Queued,
    Running,
    Completed,
    Failed,
    Cancelled,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolDef {
    pub id: String,
    pub name: String,
    pub description: String,
    pub category: String,
    pub requires_admin: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CognitiveStatus {
    pub axiom: AxiomStatus,
    pub eve: EveStatus,
    pub adam: AdamStatus,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AxiomStatus {
    pub enabled: bool,
    pub memories_stored: u64,
    pub last_recall: Option<String>,
    pub checkpoints_dir: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EveStatus {
    pub enabled: bool,
    pub personas_available: Vec<String>,
    pub last_session: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AdamStatus {
    pub enabled: bool,
    pub genome_version: String,
    pub beliefs_count: u64,
    pub skills_count: u64,
    pub mutations_pending: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LogEntry {
    pub timestamp: DateTime<Utc>,
    pub level: String,
    pub target: String,
    pub message: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct QueryRequest {
    pub text: String,
    pub provider: Option<String>,
    pub model: Option<String>,
    pub execute_tools: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct QueryResponse {
    pub session_id: String,
    pub response_text: String,
    pub provider_used: String,
    pub model_used: String,
    pub tools_executed: Vec<String>,
    pub duration_ms: u64,
}
