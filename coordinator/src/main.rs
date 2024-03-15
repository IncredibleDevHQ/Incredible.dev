use anyhow::Result;
use log::info;
use once_cell::sync::Lazy;

mod controller;
mod models;
mod routes;

use core::result::Result::Ok;
use std::env;

#[allow(unused)]
#[derive(Debug, Clone)]
pub struct Configuration {
    environment: String,
    code_search_url: String,
    context_generator_url: String,
    code_understanding_url: String,
    code_modifier_url: String,
    openai_url: String,
    openai_api_key: String,
    openai_model: String,
}

/// Okay so,
/// First we get the user query into the system
/// Then we call the qiestion generator for the question coming in
/// Then we get answers for those questions
/// Once we have all of them we want to call context generator
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
            context_generator_url: env::var("CONTEXT_GENERATOR_URL")
                .unwrap_or_else(|_| "http://127.0.0.1:3000".to_string()),
            code_understanding_url: env::var("CODE_UNDERSTANDING_URL")
                .unwrap_or_else(|_| "http://127.0.0.1:3000".to_string()),
            code_modifier_url: env::var("CODE_MODIFIER_URL")
                .unwrap_or_else(|_| "http://127.0.0.1:3000".to_string()),
            openai_url: env::var("OPENAI_URL")
                .unwrap_or_else(|_| "https://api.openai.com".to_string()),
            openai_api_key: env::var("OPENAI_API_KEY")
                .unwrap_or_else(|_| "default_api_key".to_string()),
            openai_model: env::var("OPENAI_MODEL")
                .unwrap_or_else(|_| "gpt-4-1106-preview".to_string()),
        }
    }
}

static CONFIG: Lazy<Configuration> = Lazy::new(|| Configuration::load_from_env());

#[tokio::main]
async fn main() -> Result<()> {
    env_logger::init();
    dotenv::dotenv().ok();

    info!("Loaded configuration: {:?}", *CONFIG);

    let coordinator_routes = routes::coordinator();
    warp::serve(coordinator_routes)
        .run(([0, 0, 0, 0], 3001))
        .await;
    info!("Started web server on http://localhost:3001");

    Ok(())
}
