use bincode::de;
use regex_syntax::ast::print;
use reqwest;
use serde::{Deserialize, Serialize};
use serde_json::json;
use std::error::Error;

#[derive(Serialize, Deserialize, Debug)]
pub struct SymbolSearchResult {
    path: String,
    snippet: String,
    start_line: u32,
    end_line: u32,
}

#[derive(Serialize, Deserialize, Debug)]
pub struct SymbolCodeChunk {
    pub relative_path: String,
    pub snippets: String,
    pub start_line: u32,
    pub end_line: u32,
    pub index: usize,
}

pub async fn symbol_search(query: &str) -> Result<Vec<SymbolCodeChunk>, Box<dyn Error>> {
    let base_url = "http://localhost:3000";
    let namespace = "bloop-ai";
    let client = reqwest::Client::new();
    let url = format!("{}/symbols", base_url);

    let response = client
        .post(&url)
        .header("Content-Type", "application/json")
        .json(&json!({ "query": query, "repo_name": namespace }))
        .send()
        .await?;

    if response.status() != reqwest::StatusCode::OK {
        return Err(Box::new(std::io::Error::new(
            std::io::ErrorKind::Other,
            "Error in SymbolSearch",
        )));
    }

    let search_results: Vec<SymbolSearchResult> = response.json().await?;

    println!("search_results: {:?}", search_results);
    // Process search_results to create CodeChunks...
    // Implement the logic similar to JavaScript's map and filter here
    // Note: The ranking functionality needs to be implemented or integrated

    // Placeholder for processed code chunks

    let results = search_results
        .into_iter()
        .map(|result| SymbolCodeChunk {
            relative_path: result.path,
            snippets: result.snippet,
            start_line: result.start_line,
            end_line: result.end_line,
            index: 0,
        })
        .collect::<Vec<_>>();

    println!("shankar: {:?}", results);
    Ok(results)
}
