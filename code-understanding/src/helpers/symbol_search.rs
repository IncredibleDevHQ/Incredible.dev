use reqwest;
use serde_json::json;
use anyhow::Error;
extern crate common;

use common::models::CodeChunk;

use crate::config::get_search_server_url;

pub async fn symbol_search(
    query: &str,
    repo_name: &str,
) -> Result<Vec<CodeChunk>, Error> {
    let base_url = get_search_server_url(); 
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
        // return error message with status code 
        return Err(Error::msg(format!(
            "Symbol search failed with status code: {:?}, Error: {:?}",
            response.status(), response.text().await
        )));
       
    }

    let search_results: Vec<CodeChunk> = response.json().await?;

    Ok(search_results)
}
