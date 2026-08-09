use std::{io, time::Duration};

use chimera_core::{AgentTask, CognitiveStatus, LogEntry, ProviderStatus, SystemStatus, TaskStatus};
use chrono::Utc;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Tab {
    Dashboard,
    Agents,
    Models,
    Tools,
    Cognitive,
    Console,
    Settings,
}

impl Tab {
    pub const ALL: &[Tab] = &[
        Tab::Dashboard,
        Tab::Agents,
        Tab::Models,
        Tab::Tools,
        Tab::Cognitive,
        Tab::Console,
        Tab::Settings,
    ];

    pub fn title(&self) -> &'static str {
        match self {
            Tab::Dashboard => "Dashboard",
            Tab::Agents => "Agents",
            Tab::Models => "Models",
            Tab::Tools => "Tools",
            Tab::Cognitive => "Cognitive",
            Tab::Console => "Console",
            Tab::Settings => "Settings",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum InputMode {
    Normal,
    Editing,
    Querying,
}

pub struct App {
    pub running: bool,
    pub demo_mode: bool,
    pub tab: Tab,
    pub input_mode: InputMode,
    pub input: String,
    pub cursor_position: usize,
    pub status: Option<SystemStatus>,
    pub providers: Vec<ProviderStatus>,
    pub agents: Vec<AgentTask>,
    pub cognitive: Option<CognitiveStatus>,
    pub logs: Vec<LogEntry>,
    pub log_scroll: u16,
    pub agent_scroll: u16,
    pub tool_scroll: u16,
    pub selected_provider: usize,
    pub selected_agent: usize,
    pub selected_tool: usize,
    pub api_host: String,
    pub api_port: u16,
    pub last_error: Option<String>,
    pub notification: Option<(String, std::time::Instant)>,
}

impl App {
    pub fn new(demo_mode: bool, api_host: String, api_port: u16) -> Self {
        let mut app = Self {
            running: true,
            demo_mode,
            tab: Tab::Dashboard,
            input_mode: InputMode::Normal,
            input: String::new(),
            cursor_position: 0,
            status: None,
            providers: Vec::new(),
            agents: Vec::new(),
            cognitive: None,
            logs: Vec::new(),
            log_scroll: 0,
            agent_scroll: 0,
            tool_scroll: 0,
            selected_provider: 0,
            selected_agent: 0,
            selected_tool: 0,
            api_host,
            api_port,
            last_error: None,
            notification: None,
        };
        if demo_mode {
            app.load_demo_data();
        }
        app
    }

    pub fn load_demo_data(&mut self) {
        self.status = Some(SystemStatus {
            version: "2.0.0".into(),
            uptime_seconds: 1245,
            state: chimera_core::RuntimeState::Online,
            providers_online: 4,
            providers_total: 5,
            active_agents: 3,
            queued_tasks: 2,
            memory_used_mb: 512,
            cpu_percent: 12.5,
        });
        self.providers = vec![
            ProviderStatus {
                id: "openai".into(),
                name: "OpenAI".into(),
                enabled: true,
                healthy: true,
                latency_ms: Some(340),
                default_model: "gpt-4o".into(),
                models: vec!["gpt-4o".into(), "gpt-4o-mini".into(), "o3-mini".into()],
                last_error: None,
                last_checked: Utc::now(),
            },
            ProviderStatus {
                id: "anthropic".into(),
                name: "Anthropic".into(),
                enabled: true,
                healthy: true,
                latency_ms: Some(420),
                default_model: "claude-3-5-sonnet".into(),
                models: vec!["claude-3-5-sonnet".into(), "claude-3-5-haiku".into()],
                last_error: None,
                last_checked: Utc::now(),
            },
            ProviderStatus {
                id: "google".into(),
                name: "Google Gemini".into(),
                enabled: true,
                healthy: true,
                latency_ms: Some(280),
                default_model: "gemini-2.0-flash".into(),
                models: vec!["gemini-2.0-flash".into(), "gemini-1.5-pro".into()],
                last_error: None,
                last_checked: Utc::now(),
            },
            ProviderStatus {
                id: "groq".into(),
                name: "Groq".into(),
                enabled: true,
                healthy: true,
                latency_ms: Some(120),
                default_model: "llama-3.3-70b".into(),
                models: vec!["llama-3.3-70b".into(), "mixtral-8x7b".into()],
                last_error: None,
                last_checked: Utc::now(),
            },
            ProviderStatus {
                id: "ollama".into(),
                name: "Ollama (Local)".into(),
                enabled: true,
                healthy: false,
                latency_ms: None,
                default_model: "llama3.2".into(),
                models: vec!["llama3.2".into(), "mistral".into()],
                last_error: Some("Connection refused: localhost:11434".into()),
                last_checked: Utc::now(),
            },
        ];
        self.agents = vec![
            AgentTask {
                id: "agent-001".into(),
                name: "Code Review Agent".into(),
                status: TaskStatus::Running,
                provider: "anthropic".into(),
                model: "claude-3-5-sonnet".into(),
                prompt_preview: "Review the authentication module for CWE-863...".into(),
                created_at: Utc::now(),
                completed_at: None,
                result_preview: None,
            },
            AgentTask {
                id: "agent-002".into(),
                name: "RAG Indexer".into(),
                status: TaskStatus::Completed,
                provider: "openai".into(),
                model: "gpt-4o-mini".into(),
                prompt_preview: "Index and embed all markdown docs...".into(),
                created_at: Utc::now(),
                completed_at: Some(Utc::now()),
                result_preview: Some("Indexed 47 documents, 12,402 chunks.".into()),
            },
            AgentTask {
                id: "agent-003".into(),
                name: "Security Auditor".into(),
                status: TaskStatus::Queued,
                provider: "groq".into(),
                model: "llama-3.3-70b".into(),
                prompt_preview: "Run secret scanning on uploaded files...".into(),
                created_at: Utc::now(),
                completed_at: None,
                result_preview: None,
            },
        ];
        self.cognitive = Some(CognitiveStatus {
            axiom: chimera_core::AxiomStatus {
                enabled: true,
                memories_stored: 1847,
                last_recall: Some("Agent orchestration patterns for OpenChimera v2".into()),
                checkpoints_dir: "D:\\AXIOM-AETHER\\checkpoints".into(),
            },
            eve: chimera_core::EveStatus {
                enabled: true,
                personas_available: vec!["general".into(), "developer".into(), "researcher".into()],
                last_session: Some("UX validation of TUI dashboard — Approve".into()),
            },
            adam: chimera_core::AdamStatus {
                enabled: true,
                genome_version: "1.4.0".into(),
                beliefs_count: 312,
                skills_count: 28,
                mutations_pending: 2,
            },
        });
        self.logs = vec![
            LogEntry { timestamp: Utc::now(), level: "INFO".into(), target: "openchimera".into(), message: "Kernel boot sequence complete".into() },
            LogEntry { timestamp: Utc::now(), level: "INFO".into(), target: "providers".into(), message: "OpenAI provider online (latency: 340ms)".into() },
            LogEntry { timestamp: Utc::now(), level: "INFO".into(), target: "providers".into(), message: "Anthropic provider online (latency: 420ms)".into() },
            LogEntry { timestamp: Utc::now(), level: "WARN".into(), target: "providers".into(), message: "Ollama provider offline: connection refused".into() },
            LogEntry { timestamp: Utc::now(), level: "INFO".into(), target: "cognitive".into(), message: "AXIOM memory loaded: 1847 entries".into() },
            LogEntry { timestamp: Utc::now(), level: "INFO".into(), target: "cognitive".into(), message: "ADAM genome v1.4.0 active".into() },
            LogEntry { timestamp: Utc::now(), level: "INFO".into(), target: "agent-orchestrator".into(), message: "Spawned Code Review Agent (claude-3-5-sonnet)".into() },
        ];
    }

    pub fn next_tab(&mut self) {
        let idx = Tab::ALL.iter().position(|t| *t == self.tab).unwrap_or(0);
        let next = (idx + 1) % Tab::ALL.len();
        self.tab = Tab::ALL[next];
    }

    pub fn prev_tab(&mut self) {
        let idx = Tab::ALL.iter().position(|t| *t == self.tab).unwrap_or(0);
        let prev = (idx + Tab::ALL.len() - 1) % Tab::ALL.len();
        self.tab = Tab::ALL[prev];
    }

    pub fn push_notification(&mut self, msg: String) {
        self.notification = Some((msg, std::time::Instant::now()));
    }

    pub fn expire_notification(&mut self) {
        if let Some((_, t)) = &self.notification {
            if t.elapsed() > Duration::from_secs(4) {
                self.notification = None;
            }
        }
    }
}
