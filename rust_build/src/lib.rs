use pyo3::prelude::*;
use pyo3::wrap_pyfunction;
use std::collections::HashMap;
use std::sync::Arc;
use tokio::sync::Mutex;
use std::time::Duration;
use futures::future::{select, Either};
use futures::stream::{FuturesUnordered, StreamExt};
use serde::{Deserialize, Serialize};
use reqwest::Client;

// --- Task 1: Consensus Engine ---

#[derive(Serialize, Deserialize, Debug)]
struct ChatCompletionRequest {
    model: String,
    messages: Vec<HashMap<String, String>>,
    temperature: Option<f32>,
    max_tokens: Option<i32>,
}

#[derive(Serialize, Deserialize, Debug)]
struct ChatCompletionResponse {
    choices: Vec<Choice>,
}

#[derive(Serialize, Deserialize, Debug)]
struct Choice {
    message: Message,
}

#[derive(Serialize, Deserialize, Debug)]
struct Message {
    content: String,
}

async fn query_model(client: &Client, url: &str, payload: &serde_json::Value, api_key: Option<&str>) -> Result<String, String> {
    let mut req = client.post(url).json(payload);
    
    if let Some(key) = api_key {
        req = req.header("Authorization", format!("Bearer {}", key));
    }

    match req.send().await {
        Ok(resp) => {
            if resp.status().is_success() {
                match resp.json::<serde_json::Value>().await {
                    Ok(json) => {
                        // Extract content slightly generically
                        if let Some(choices) = json.get("choices") {
                            if let Some(first) = choices.get(0) {
                                if let Some(msg) = first.get("message") {
                                    if let Some(content) = msg.get("content") {
                                        return Ok(content.as_str().unwrap_or("").to_string());
                                    }
                                }
                            }
                        }
                        // Fallback for simple text response if needed
                        Ok(json.to_string())
                    }
                    Err(e) => Err(format!("JSON Parse Error: {}", e)),
                }
            } else {
                Err(format!("HTTP Error: {}", resp.status()))
            }
        }
        Err(e) => Err(format!("Network Error: {}", e)),
    }
}

#[pyfunction]
fn run_consensus(py: Python, payload_json: String, grace_ms: u64, endpoints: Vec<(String, String, Option<String>)>) -> PyResult<String> {
    // endpoints: [(name, url, api_key), ...]
    let rt = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .unwrap();

    let payload: serde_json::Value = serde_json::from_str(&payload_json).map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e.to_string()))?;
    
    let result = rt.block_on(async {
        let client = Client::new();
        let mut futures = FuturesUnordered::new();

        for (name, url, key) in endpoints {
            let client_clone = client.clone();
            let payload_clone = payload.clone();
            let name_clone = name.clone();
            
            futures.push(async move {
                let res = query_model(&client_clone, &url, &payload_clone, key.as_deref()).await;
                (name_clone, res)
            });
        }

        let mut best_result: Option<String> = None;
        let mut completed_count = 0;
        let total = futures.len();

        // First Good Answer Wins logic with Grace Period
        // Simplified: Return absolute first success for now, or wait grace period if we want to compare.
        // The prompt asked for: "Return the first successful result, hold for a configurable grace window... then abort"
        
        let start_time = std::time::Instant::now();
        let mut first_success_time: Option<std::time::Instant> = None;
        
        loop {
            tokio::select! {
                Some((name, res)) = futures.next() => {
                    completed_count += 1;
                    match res {
                        Ok(content) => {
                            if best_result.is_none() {
                                best_result = Some(content);
                                first_success_time = Some(std::time::Instant::now());
                                // Start grace period timer effectively
                            }
                            // In a real implementation, we would compare quality here during grace period
                        }
                        Err(e) => {
                            // Log error?
                        }
                    }
                }
                _ = tokio::time::sleep(Duration::from_millis(100)), if first_success_time.is_some() => {
                     // Check if grace period expired
                     if let Some(t) = first_success_time {
                         if t.elapsed().as_millis() as u64 >= grace_ms {
                             break;
                         }
                     }
                }
                else => {
                    if completed_count == total {
                        break;
                    }
                }
            }
            
            // If we have a result and we want to just return immediately (aggressive mode)
            // or if grace period logic handled above breaks the loop.
            if first_success_time.is_some() {
                 if first_success_time.unwrap().elapsed().as_millis() as u64 >= grace_ms {
                     break;
                 }
            }
        }

        best_result.unwrap_or_else(|| "{\"error\": \"All models failed\"}".to_string())
    });

    Ok(result)
}

// --- Task 2: Token Optimizer ---

#[pyfunction]
fn compress_prompt(text: String, max_tokens: usize, strategy: String) -> String {
    // Simple approximation: 1 token ~= 4 chars. Real tokenizer would be better but requires huggingface/tokenizers crate
    let est_tokens = text.len() / 4;
    
    if est_tokens <= max_tokens {
        return text;
    }

    match strategy.as_str() {
        "truncate_tail" => {
            let max_chars = max_tokens * 4;
            if text.len() > max_chars {
                text[..max_chars].to_string()
            } else {
                text
            }
        },
        "sliding_window" => {
            // Keep first 20%, last 80%
            let target_chars = max_tokens * 4;
            let head_chars = (target_chars as f32 * 0.2) as usize;
            let tail_chars = target_chars - head_chars;
            
            if text.len() <= target_chars {
                return text;
            }
            
            let head = &text[..head_chars];
            let tail = &text[text.len() - tail_chars..];
            format!("{}... [snip] ...{}", head, tail)
        },
        "semantic" => {
            // Split by sentences (approximated by dot space)
            // This is a naive implementation for speed
            let sentences: Vec<&str> = text.split(". ").collect();
            let mut result = String::new();
            let mut current_len = 0;
            let target_chars = max_tokens * 4;
            
            // Prioritize last sentences
            for s in sentences.iter().rev() {
                if current_len + s.len() < target_chars {
                    if !result.is_empty() {
                        result.insert_str(0, ". ");
                    }
                    result.insert_str(0, s);
                    current_len += s.len();
                } else {
                    break;
                }
            }
            result
        },
        _ => text // Default
    }
}

// --- Task 3: Vector Search ---

fn cosine_similarity(a: &[f32], b: &[f32]) -> f32 {
    let dot_product: f32 = a.iter().zip(b).map(|(x, y)| x * y).sum();
    let norm_a: f32 = a.iter().map(|x| x * x).sum::<f32>().sqrt();
    let norm_b: f32 = b.iter().map(|x| x * x).sum::<f32>().sqrt();
    
    if norm_a == 0.0 || norm_b == 0.0 {
        return 0.0;
    }
    
    dot_product / (norm_a * norm_b)
}

#[pyfunction]
fn similarity_search(query_embedding: Vec<f32>, stored_embeddings: Vec<Vec<f32>>, top_k: usize) -> Vec<usize> {
    let mut scores: Vec<(usize, f32)> = stored_embeddings.iter().enumerate()
        .map(|(i, emb)| (i, cosine_similarity(&query_embedding, emb)))
        .collect();
        
    // Sort descending by score
    scores.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
    
    scores.iter().take(top_k).map(|(i, _)| *i).collect()
}

#[pymodule]
fn chimera_core(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(run_consensus, m)?)?;
    m.add_function(wrap_pyfunction!(compress_prompt, m)?)?;
    m.add_function(wrap_pyfunction!(similarity_search, m)?)?;
    Ok(())
}
