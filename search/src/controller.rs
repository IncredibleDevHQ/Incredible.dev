use anyhow::Context;
use anyhow::Error;

use std::convert::Infallible;
use std::ffi::c_long;
use std::sync::Arc;
use warp::{self, http::StatusCode};

use crate::db;
use crate::db::DbConnect;
use crate::models::SymbolSearchRequest;
use crate::search::code_search::code_search;
use crate::{search::semantic::Semantic, Configuration};
use anyhow::Result;
use md5::compute;
use reqwest;
use serde::{Deserialize, Serialize};
use std::env;

#[derive(Debug, Serialize, Deserialize)]
struct ApiResponse {
    result: CollectionStatus,
    status: String,
    time: f64,
}

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
) -> Result<impl warp::Reply, Infallible> {
    let namespace = generate_qdrant_index_name(&search_request.repo_name);
    let is_collection_available = get_collection_status(
        env::var("SEMANTIC_DB_URL").expect("SEMANTIC_DB_URL must be set"),
        &namespace, // &search_request.repo_name,
        &env::var("QDRANT_CLOUD_API_KEY").expect("QDRANT_CLOUD_API_KEY must be set"),
    )
    .await;
    println!("Rest: {:?}", is_collection_available);
    let configuration = Configuration {
        symbol_collection_name: if is_collection_available {
            namespace
        } else {
            env::var("SYMBOL_COLLECTION_NAME").expect("SYMBOL_COLLECTION_NAME must be set")
        },
        semantic_db_url: env::var("SEMANTIC_DB_URL").expect("SEMANTIC_DB_URL must be set"),
        tokenizer_path: env::var("TOKENIZER_PATH").unwrap_or("model/tokenizer.json".to_string()),
        model_path: env::var("MODEL_PATH").unwrap_or("model/model.onnx".to_string()),
        qdrant_api_key: env::var("QDRANT_CLOUD_API_KEY").expect("QDRANT_CLOUD_API_KEY must be set"),
    };

    // pritn configuration
    println!("Configuration: {:?}", configuration);

    let db: Result<DbConnect, Error> = db::init_db(configuration)
        .await
        .context("Failed to initialize db");

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

async fn get_collection_status(
    mut base_url: String,
    collection_name: &String,
    apikey: &str,
) -> bool {
    // Check if the base URL contains the port 6334 and replace it with 6333
    if base_url.contains(":6334") {
        base_url = base_url.replace(":6334", ":6333");
    }

    // The collection name seems to be hardcoded, so you might not need the `field` parameter.
    let url = format!("{}/collections/{}", base_url, collection_name);
    let api_key = apikey;

    println!("Url: {}", url);

    let client = reqwest::Client::new();
    let response = client.get(url).header("Api-Key", api_key).send().await;

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
