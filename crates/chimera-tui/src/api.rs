use chimera_core::{CognitiveStatus, ProviderStatus, SystemStatus};
use color_eyre::Result;

#[derive(Clone)]
pub struct ApiClient {
    client: reqwest::Client,
    base_url: String,
}

impl ApiClient {
    pub fn new(host: String, port: u16) -> Self {
        Self {
            client: reqwest::Client::new(),
            base_url: format!("http://{}:{}", host, port),
        }
    }

    pub async fn fetch_status(&self) -> Result<SystemStatus> {
        let url = format!("{}/api/v2/status", self.base_url);
        let resp = self.client.get(&url).timeout(std::time::Duration::from_secs(5)).send().await?;
        let status = resp.json::<SystemStatus>().await?;
        Ok(status)
    }

    pub async fn fetch_providers(&self) -> Result<Vec<ProviderStatus>> {
        let url = format!("{}/api/v2/providers", self.base_url);
        let resp = self.client.get(&url).timeout(std::time::Duration::from_secs(5)).send().await?;
        let providers = resp.json::<Vec<ProviderStatus>>().await?;
        Ok(providers)
    }

    pub async fn fetch_cognitive(&self) -> Result<CognitiveStatus> {
        let url = format!("{}/api/v2/cognitive/status", self.base_url);
        let resp = self.client.get(&url).timeout(std::time::Duration::from_secs(5)).send().await?;
        let cog = resp.json::<CognitiveStatus>().await?;
        Ok(cog)
    }
}
