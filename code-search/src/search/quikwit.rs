use crate::{AppState, CLIENT};
use anyhow::{Error, Result};
use common::ast::graph_code_pluck::ContentDocument;
use log::{debug, error};
use serde::{Deserialize, Serialize};
use std::collections::HashSet;
use std::sync::Arc;

#[derive(Debug, Serialize, Deserialize)]
struct BodyRes {
    query: String,
    max_hits: i32,
}

#[derive(Debug, Serialize, Deserialize)]
struct ApiResponse {
    num_hits: i32,            // Change the type to i32 or another appropriate numeric type
    elapsed_time_micros: i64, // Change the type to i32 or another appropriate numeric type
    hits: Vec<ResultItem>,
    errors: Vec<String>,
}

#[derive(Debug, Serialize, Deserialize)]
struct ResultItem {
    relative_path: String,
    repo_name: String,
    lang: Option<String>,
    content: String,
    symbols: String,
    line_end_indices: Vec<u8>,
    symbol_locations: Vec<u8>,
    is_directory: bool,
    last_commit: String,
    repo_ref: String,
    repo_disk_path: String,
    unique_hash: String,
}

// FIXME: This is likely very inefficient for large numbers of files, Quickwit surprisingly
// doesn't choke for 100-150 files in a non-concurrent environment. For larger repos we may
// want to go with a paginated approach. We will revisit this once we start choking.
pub async fn get_all_files_for_repo(
    index_name: &str,
    repo_name: &str,
    app_state: Arc<AppState>,
) -> Result<Vec<ContentDocument>> {
    let config = app_state.configuration.clone();

    let base_url = config.quikwit_db_url.clone();

    let query = "*".to_string();

    let json_data = BodyRes {
        query,
        max_hits: 1000, // This is a very high number, if we actually have to serve for 1000 files, this will surly die. We should consider pagination in the near future.
    };

    let json_string = serde_json::to_string(&json_data).expect("Failed to serialize object");

    let url = format!("{}/api/v1/{}/search", base_url, index_name);

    let response = CLIENT
        .post(url)
        .header("Content-Type", "application/json")
        .body(json_string)
        .send()
        .await?;

    let mut response_array: Vec<ContentDocument> = Vec::new();

    if response.status().is_success() {
        let response_text: String = response.text().await?;

        let parsed_response: Result<ApiResponse, serde_json::Error> =
            serde_json::from_str(&response_text);

        match parsed_response {
            Ok(api_response) => {
                debug!("Number of files found: {:?}", api_response.hits.len());
                for result_item in api_response.hits {
                    if repo_name == result_item.repo_name {
                        response_array.push(ContentDocument {
                            relative_path: result_item.relative_path,
                            repo_name: result_item.repo_name,
                            lang: result_item.lang,
                            content: result_item.content,
                            repo_ref: result_item.repo_ref,
                            line_end_indices: result_item.line_end_indices,
                            symbol_locations: result_item.symbol_locations,
                            symbols: result_item.symbols,
                        });
                    }
                }
            }
            Err(err) => {
                error!("Failed to parse JSON response: {}", err);
            }
        }
    } else {
        error!("Request was not successful: {}", response.status());
    }

    if !response_array.is_empty() {
        Ok(response_array.clone())
    } else {
        Ok(vec![])
    }
}

pub async fn get_file_from_quickwit(
    index_name: &str,
    search_field: &str,
    search_query: &str,
    app_state: Arc<AppState>,
) -> Result<Option<ContentDocument>> {
    let query = if !search_field.is_empty() {
        format!("{}:{}", search_field, search_query)
    } else {
        search_query.to_owned()
    };
    let response_array = search_quickwit(index_name, &query, app_state).await?;
    let filtered_response_array: Vec<ContentDocument> = response_array
        .into_iter()
        .filter((|doc| doc.relative_path == search_query))
        .collect();

    let paths: Vec<_> = filtered_response_array
        .clone()
        .into_iter()
        .map(|c| c.relative_path)
        .collect::<HashSet<_>>() // Removes duplicates
        .into_iter()
        .collect::<Vec<_>>();
    debug!("Quickwit paths: {:?}", paths);

    return Ok(filtered_response_array.first().or(None).cloned());
}

pub async fn search_quickwit(
    index_name: &str,
    query: &str,
    app_state: Arc<AppState>,
) -> Result<Vec<ContentDocument>, Error> {
    let config = app_state.configuration.clone();

    let base_url = config.quikwit_db_url.clone();

    let json_data = BodyRes {
        query: query.to_string(),
        max_hits: 10,
    };

    let json_string = serde_json::to_string(&json_data).expect("Failed to serialize object");

    let url = format!("{}/api/v1/{}/search", base_url, index_name);

    let response = CLIENT
        .post(url)
        .header("Content-Type", "application/json")
        .body(json_string)
        .send()
        .await?;

    let mut response_array: Vec<ContentDocument> = Vec::new();

    if response.status().is_success() {
        let response_text: String = response.text().await?;

        let parsed_response: Result<ApiResponse, serde_json::Error> =
            serde_json::from_str(&response_text);

        match parsed_response {
            Ok(api_response) => {
                for result_item in api_response.hits {
                    response_array.push(ContentDocument {
                        relative_path: result_item.relative_path,
                        repo_name: result_item.repo_name,
                        lang: result_item.lang,
                        content: result_item.content,
                        repo_ref: result_item.repo_ref,
                        line_end_indices: result_item.line_end_indices,
                        symbol_locations: result_item.symbol_locations,
                        symbols: result_item.symbols,
                    });
                }
            }
            Err(err) => {
                error!("Failed to parse JSON response: {}", err);
            }
        }
    } else {
        error!("Request was not successful: {}", response.status());
    }

    Ok(response_array)
}
