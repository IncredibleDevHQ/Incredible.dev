use anyhow::Result;
use log::info;
use once_cell::sync::Lazy;

mod agent;
mod controller;
mod diff;
mod models;
mod routes;
mod utils;

use core::result::Result::Ok;
use std::env;

#[derive(Debug, Clone)]
#[allow(unused)]
pub struct Configuration {
    environment: String,
    code_search_url: String,
    openai_url: String,
    openai_api_key: String,
    openai_model: String,
}

impl Configuration {
    fn load_from_env() -> Self {
        let environment = std::env::var("RUST_ENV").unwrap_or_else(|_| "development".to_string());
        let env_file = format!(".env.{}", environment);

        info!("Loading configurations from {}", env_file);
        dotenv::from_filename(env_file).ok();
        Self {
            environment: env::var("ENVIRONMENT").unwrap_or_else(|_| "development".to_string()),
            code_search_url: env::var("CODE_SEARCH_URL")
                .unwrap_or_else(|_| "http://127.0.0.1:3000".to_string()),
            openai_url: env::var("OPENAI_URL")
                .unwrap_or_else(|_| "https://api.openai.com".to_string()),
            openai_api_key: env::var("OPENAI_API_KEY").unwrap_or_else(|_| {
                "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".to_string()
            }),
            openai_model: env::var("OPENAI_MODEL")
                .unwrap_or_else(|_| "gpt-4-1106-preview".to_string()),
        }
    }
}

static CONFIG: Lazy<Configuration> = Lazy::new(|| Configuration::load_from_env());

#[tokio::main]
async fn main() -> Result<()> {
    env_logger::init();

    info!("Loaded configuration: {:?}", *CONFIG);

    let modification_routes = routes::modify_code();
    warp::serve(modification_routes)
        .run(([0, 0, 0, 0], 3001))
        .await;
    info!("Started web server on http://localhost:3001");

    Ok(())
}
