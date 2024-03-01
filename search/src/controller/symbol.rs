use anyhow::Context;
use anyhow::Error;

use std::convert::Infallible;
use std::sync::Arc;
use warp::{self, http::StatusCode};

use crate::db;
use crate::db::DbConnect;
use crate::models::SymbolSearchRequest;
use crate::search::code_search::code_search;
use crate::AppState;
use crate::{search::semantic::Semantic, Configuration};
use anyhow::Result;
use md5::compute;
use reqwest;
use serde::{Deserialize, Serialize};
use std::env;

#[derive(Debug, Serialize, Deserialize)]
struct CollectionStatus {
    status: String,
    optimizer_status: String,
    vectors_count: u64,
    indexed_vectors_count: u64,
    points_count: u64,
    segments_count: u64,
}

pub async fn symbol_search(
    search_request: SymbolSearchRequest,
    app_state: Arc<AppState>,
) -> Result<impl warp::Reply, Infallible> {
    let config = app_state.configuration.clone();
    // Qdrant key is only set while using Qdrant Cloud, otherwise we'll be using the local Qdrant instance.
    // access the qdrant key from the app_state
    let qdrant_key = config.qdrant_api_key;

    // namespace is set to repo name from the search request if the qdrant key is not set
    let namespace = if qdrant_key.is_none() {
        search_request.repo_name
    } else {
        generate_qdrant_index_name(&search_request.repo_name)
    };

    // check if the collection is available, use app state to access the configuration

    let is_collection_available = get_collection_status(
        config.semantic_db_url,
        &namespace, // &search_request.repo_name,
        qdrant_key,
    ).await;

    let db = app_state.db_connection;

    match code_search(&search_request.query, &search_request.repo_name, db).await {
        Ok(chunks) => Ok(warp::reply::with_status(
            warp::reply::json(&chunks),
            StatusCode::OK,
        )),
        Err(e) => Ok(warp::reply::with_status(
            warp::reply::json(&format!("Error: {}", e)),
            StatusCode::INTERNAL_SERVER_ERROR,
        )),
    }
}

// check if qdrant collection is available
async fn get_collection_status(
    mut base_url: String,
    collection_name: &String,
    apikey: Option<String>,
) -> bool {
    // Check if the base URL contains the port 6334 and replace it with 6333
    if base_url.contains(":6334") {
        base_url = base_url.replace(":6334", ":6333");
    }

    // The collection name seems to be hardcoded, so you might not need the `field` parameter.
    let url = format!("{}/collections/{}", base_url, collection_name);
    let api_key = apikey;

    println!("Url: {}", url);

    let client = Client::new().get(&url);

    let client = if let Some(key) = api_key {
        client.header(
            "Api-Key",
            HeaderValue::from_str(&key),
        )
    } else {
        client
    };
    let response = client.send().await;

    match response {
        Ok(resp) => resp.status().is_success(),
        Err(e) => {
            eprintln!("Error occurred: {}", e);
            false
        }
    }
}

pub fn generate_qdrant_index_name(namespace: &str) -> String {
    let repo_name = namespace.split("/").last().unwrap();
    let version = namespace.split("/").nth(0).unwrap();
    let md5_index_id = compute(namespace);
    // create a hex string
    let new_index_id = format!("{:x}", md5_index_id);
    let index_name = format!(
        "{}-{}-{}-documents-symbols",
        version, repo_name, new_index_id
    );
    return index_name;
}
