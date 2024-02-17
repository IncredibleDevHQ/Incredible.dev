use anyhow::{Error, Result};
use serde::{Deserialize, Serialize};
use std::collections::HashSet;
use std::env;

use crate::CLIENT;
use crate::search::code_search::ContentDocument;

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

pub async fn get_file_from_quickwit(
    index_name: &str,
    search_field: &str,
    search_query: &str,
) -> Result<Option<ContentDocument>> {
    let response_array = search_quickwit(index_name, search_field, search_query).await?;

    let cloned_response_array = response_array.clone(); // Clone the response_array

    let paths: Vec<_> = cloned_response_array
        .into_iter()
        .map(|c| c.relative_path)
        .collect::<HashSet<_>>() // Removes duplicates
        .into_iter()
        .collect::<Vec<_>>();
    println!("Quickwit paths: {:?}", paths);

    Ok(response_array)
}

pub async fn search_quickwit(
    index_name: &str,
    search_field: &str,
    search_query: &str,
) -> Result<Option<ContentDocument>, Error> {
    let base_url = env::var("QUICKWIT_DB_URL").expect("QUICKWIT_DB_URL must be set");

    let query = if !search_field.is_empty() {
        format!("{}:{}", search_field, search_query)
    } else {
        search_query.to_owned()
    };

    let json_data = BodyRes {
        query,
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
                    if search_query == result_item.relative_path {
                        println!("Found a match: {}", search_query);
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
                println!("Failed to parse JSON response: {}", err);
            }
        }
    } else {
        println!("Request was not successful: {}", response.status());
    }

    if !response_array.is_empty() {
        Ok(Some(response_array[0].clone())) // Return the first ContentDocument
    } else {
        Ok(None) // No ContentDocument found
    }
}
