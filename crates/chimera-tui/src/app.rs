use chimera_core::*;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CurrentTab {
    Dashboard,
    Providers,
    Cognitive,
}

pub struct App {
    pub tab: CurrentTab,
    pub status: Option<SystemStatus>,
    pub providers: Vec<ProviderStatus>,
    pub agents: Vec<AgentStatus>,
    pub error: Option<String>,
}

impl App {
    pub fn new() -> Self {
        Self {
            tab: CurrentTab::Dashboard,
            status: None,
            providers: vec![],
            agents: vec![],
            error: None,
        }
    }

    pub fn next_tab(&mut self) {
        self.tab = match self.tab {
            CurrentTab::Dashboard => CurrentTab::Providers,
            CurrentTab::Providers => CurrentTab::Cognitive,
            CurrentTab::Cognitive => CurrentTab::Dashboard,
        };
    }

    pub async fn refresh(&mut self) {
        match api::fetch_status().await {
            Ok(s) => {
                self.status = Some(s);
                self.error = None;
            }
            Err(e) => self.error = Some(e.to_string()),
        }
        match api::fetch_providers().await {
            Ok(p) => self.providers = p,
            Err(_) => {}
        }
    }
}
