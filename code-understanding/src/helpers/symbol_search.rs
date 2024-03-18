use reqwest;
use serde::{Deserialize, Serialize};
use serde_json::json;
use anyhow::Error;
use crate::get_config;
extern crate common;

use common::models::CodeChunk;

#[derive(Serialize, Deserialize, Debug)]
pub struct SymbolSearchResult {
    path: String,
    snippet: String,
    start_line: usize,
    end_line: usize,
}

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

    let search_results: Vec<SymbolSearchResult> = response.json().await?;

    let results = search_results
        .into_iter()
        .map(|result| CodeChunk {
            path : result.path,
            snippet: result.snippet,
            start_line: result.start_line,
            end_line: result.end_line,
        })
        .collect::<Vec<_>>();

    Ok(results)
}
