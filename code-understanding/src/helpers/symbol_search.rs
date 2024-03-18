use reqwest;
use serde_json::json;
use anyhow::Error;
use crate::get_config;
extern crate common;

use common::models::CodeChunk;

pub async fn symbol_search(
    query: &str,
    repo_name: &str,
) -> Result<Vec<CodeChunk>, Error> {
    let base_url = &get_config().search_server_url;
    let namespace = repo_name;
    let client = reqwest::Client::new();
    let url = format!("{}/symbols", base_url);

    let response = client
        .post(&url)
        .header("Content-Type", "application/json")
        .json(&json!({ "query": query, "repo_name": namespace }))
        .send()
        .await?;

    if response.status() != reqwest::StatusCode::OK {
        return Err(Error::msg(format!(
            "Symbol Search API request returned error:  {}",
            response.status()
        )));
    }

    let search_results: Vec<CodeChunk> = response.json().await?;

    Ok(search_results)
}
