use anyhow::Result;
use log::{error, info};
use reqwest::Client;

mod agent;
mod controller;
mod models;
mod routes;
mod utils;
mod diff;

use core::result::Result::Ok;
use std::sync::Arc;

#[allow(unused)]
struct AppState {
    configuration: Configuration,
    database_connection: DatabaseConnection,
}

#[derive(Debug, Clone)]
#[allow(unused)]
pub struct Configuration {
    environment: String,
    code_search_url: String,
    openai_url: String,
    openai_api_key: String,
    openai_model: String,
}

#[derive(Debug, Clone)]
#[allow(unused)]
pub struct DatabaseConnection {
    http_client: Client,
}

async fn init_state() -> Result<AppState, anyhow::Error> {
    let environment = std::env::var("RUST_ENV").unwrap_or_else(|_| "development".to_string());
    let env_file = format!(".env.{}", environment);

    info!("Loading configurations from {}", env_file);
    dotenv::from_filename(env_file).ok();

    let configuration = Configuration {
        environment: std::env::var("ENVIRONMENT").unwrap_or("development".to_string()),
        code_search_url: std::env::var("CODE_SEARCH_URL")
            .unwrap_or("http://127.0.0.1:3000".to_string()),
        openai_url: std::env::var("OPENAI_URL").unwrap_or("https://api.openai.com".to_string()),
        openai_api_key: std::env::var("OPENAI_API_KEY")
            .unwrap_or("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".to_string()),
        openai_model: std::env::var("OPENAI_MODEL").unwrap_or("gpt-4-1106-preview".to_string()),
    };
    info!("Initialized configuration: {:?}", configuration);

    let db_client = DatabaseConnection {
        http_client: Client::new(),
    };

    Ok(AppState {
        configuration,
        database_connection: db_client,
    })
}

#[tokio::main]
async fn main() -> Result<()> {
    env_logger::init();

    // Iniitialize app state and throw error if failed
    let app_state = init_state().await;
    let app_state = match app_state {
        Ok(app_state) => Arc::new(app_state),
        Err(err) => {
            error!("Failed to initialize app state: {}", err);
            std::process::exit(1);
        }
    };

    let modification_routes = routes::modify_code(app_state);
    warp::serve(modification_routes)
        .run(([0, 0, 0, 0], 3001))
        .await;
    info!("Started web server on http://localhost:3001");

    Ok(())
}
