use anyhow::Context;
use dotenv::dotenv;
use log::{error, info};
use std::env;
use std::sync::Arc;
use warp;

mod code_navigation;
mod controller;
mod db;
mod models;
mod parser;
mod routes;
mod search;
mod snippet;
mod utilities;

extern crate reqwest;
use reqwest::Client;

#[macro_use]
extern crate lazy_static;

lazy_static! {
    static ref CLIENT: Client = Client::new();
}
#[derive(Debug, Clone)]
pub struct Configuration {
    environment: String,
    symbol_collection_name: String,
    semantic_db_url: String,
    tokenizer_path: String,
    model_path: String,
    qdrant_api_key: Option<String>,
    quikwit_db_url: String,
}

struct AppState {
    configuration: Configuration,
    db_connection: db::DbConnect, // Assuming DbConnection is your database connection type
}

async fn init_state() -> Result<AppState, anyhow::Error> {
    // load using dotenv
    dotenv().ok();
    let configuration = Configuration {
        environment: env::var("ENVIRONMENT").context("ENVRINOMENT must be set")?,
        symbol_collection_name: env::var("SYMBOL_COLLECTION_NAME")
            .context("SYMBOL_COLLECTION_NAME must be set")?,
        semantic_db_url: env::var("SEMANTIC_DB_URL").context("SEMANTIC_DB_URL must be set")?,
        tokenizer_path: env::var("TOKENIZER_PATH").context("TOKENIZER_PATH must be set")?,
        model_path: env::var("MODEL_PATH").context("MODEL_PATH must be set")?,
        quikwit_db_url: env::var("QUICKWIT_DB_URL").context("QUICKWIT_DB_URL must be set")?,
        qdrant_api_key: env::var("QDRANT_CLOUD_API_KEY").ok(),
    };

    info!("Configuration: {:#?}", configuration);
    let db_connection = db::init_db(configuration.clone()).await?;

    Ok(AppState {
        configuration,
        db_connection,
    })
}

#[tokio::main]
async fn main() {
    env_logger::init();
    // initialize the env configurations and database connection.
    let app_state = init_state().await;

    // use log library to gracefully log the error and exit the application if the app_state is not initialized.
    let app_state = match app_state {
        Ok(app_state) => Arc::new(app_state),
        Err(err) => {
            error!("Failed to initialize the app state: {}", err);
            //println!("Failed to initialize the app state: {}", err);
            std::process::exit(1);
        }
    };

    // set up the api routes
    let search_routes = routes::search_routes(app_state.clone());

    warp::serve(search_routes).run(([0, 0, 0, 0], 3003)).await;
}
