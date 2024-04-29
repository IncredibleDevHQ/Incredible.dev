use anyhow::Error;
use common::hasher::generate_qdrant_index_name;
use log::{debug, error, info};
use reqwest::header::HeaderValue;
use reqwest::Client;

use std::convert::Infallible;
use std::sync::Arc;
use warp::{self, http::StatusCode};

use crate::config::{get_qdrant_api_key, get_semantic_db_url};
use crate::{config::AppState, models::SymbolSearchRequest};
use crate::search::code_search::code_search;
use anyhow::Result;
use reqwest;
use serde::{Deserialize, Serialize};

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
    // Qdrant key is only set while using Qdrant Cloud, otherwise we'll be using the local Qdrant instance.
    // access the qdrant key from the app_state
    let qdrant_key = get_qdrant_api_key(); 

    // namespace is set to repo name from the search request if the qdrant key is not set
    let namespace = generate_qdrant_index_name(&search_request.repo_name);

    // check if the collection is available, use app state to access the configuration

    let is_collection_available = get_collection_status(
        get_semantic_db_url(),
        &namespace, // &search_request.repo_name,
        qdrant_key,
    )
    .await;

    // if there is error finding the collection status return the API error
    if is_collection_available.is_err() {
        error!("Collection doesn't exist");
        let response = format!(
            "Error validating if the collection exists: {}",
            is_collection_available.err().unwrap()
        );
        return Ok(warp::reply::with_status(
            warp::reply::json(&response),
            warp::http::StatusCode::NOT_FOUND,
        ));
    }

    let app_state_clone = Arc::clone(&app_state);
    let db = &app_state_clone.db_connection;

    match code_search(
        &search_request.query,
        &search_request.repo_name,
        &db,
        app_state,
    )
    .await
    {
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
) -> Result<bool, Error> {
    // Check if the base URL contains the port 6334 and replace it with 6333
    if base_url.contains(":6334") {
        base_url = base_url.replace(":6334", ":6333");
    }

    // The collection name seems to be hardcoded, so you might not need the `field` parameter.
    let url = format!("{}/collections/{}", base_url, collection_name);
    let api_key = apikey;

    info!("Checking status for collection {}", collection_name);
    info!("Url : {}", url);

    let client = Client::new().get(&url);

    let client = if let Some(key) = api_key {
        match HeaderValue::from_str(&key) {
            Ok(header_value) => client.header("Api-Key", header_value),
            Err(e) => {
                // log and return the error
                error!("Error occurred while checking collection status: {}", e);
                return Err(e.into());
            }
        }
    } else {
        client
    };

    let response = client.send().await;

    match response {
        Ok(resp) => return Ok(resp.status().is_success()),
        Err(e) => {
            error!(
                "Error occurred during call to check vector db status: {}",
                e
            );
            return Err(e.into());
        }
    }
}
