use anyhow::Result;
use chimera_core::*;

const API_URL: &str = "http://127.0.0.1:7870";

pub async fn fetch_status() -> Result<SystemStatus> {
    let resp = reqwest::get(format!("{}/api/v2/status", API_URL)).await?;
    let status = resp.json::<SystemStatus>().await?;
    Ok(status)
}

pub async fn fetch_providers() -> Result<Vec<ProviderStatus>> {
    let resp = reqwest::get(format!("{}/api/v2/providers", API_URL)).await?;
    let providers = resp.json::<Vec<ProviderStatus>>().await?;
    Ok(providers)
}
