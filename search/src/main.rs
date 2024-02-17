use anyhow::Context;
use dotenv::dotenv;
use std::sync::Arc;
use warp;

mod controller;
mod db;
mod graph;
mod models;
mod parser;
mod routes;
mod search;

#[derive(Debug, Clone)]
pub struct Configuration {
    symbol_collection_name: String,
    semantic_db_url: String,
    tokenizer_path: String,
    model_path: String,
    qdrant_api_key: String,
}

extern crate reqwest;
use reqwest::Client;

#[macro_use]
extern crate lazy_static;

lazy_static! {
    static ref CLIENT: Client = Client::new();
}
use std::env;

#[tokio::main]
async fn main() {
    dotenv().ok();

    let configuration = Configuration {
        symbol_collection_name: env::var("SYMBOL_COLLECTION_NAME")
            .expect("SYMBOL_COLLECTION_NAME must be set"),
        semantic_db_url: env::var("SEMANTIC_DB_URL").expect("SEMANTIC_DB_URL must be set"),
        tokenizer_path: env::var("TOKENIZER_PATH").unwrap_or("model/tokenizer.json".to_string()),
        model_path: env::var("MODEL_PATH").unwrap_or("model/model.onnx".to_string()),
        qdrant_api_key: env::var("QDRANT_CLOUD_API_KEY").expect("QDRANT_CLOUD_API_KEY must be set"),
    };

    // pritn configuration
    println!("Configuration: {:?}", configuration);

    let db = db::init_db(configuration)
        .await
        .context("Failed to initialize db");
    let search_routes = routes::search_routes();

    warp::serve(search_routes).run(([0, 0, 0, 0], 3000)).await;
}
