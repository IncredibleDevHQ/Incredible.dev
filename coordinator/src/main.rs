use anyhow::Result;
use ai_gateway::config::{initialize_ai_gateway, AIGatewayConfig};
use  common::{   config::set_redis_url,
    task_graph::redis::establish_redis_connection};

use log::{error, info};
use once_cell::sync::Lazy;

mod controller;
mod llm_ops;
mod models;
mod routes;
mod utility;

use core::result::Result::Ok;
use std::{env, sync::Mutex};

#[allow(unused)]
#[derive(Debug, Clone)]
pub struct Configuration {
    environment: String,
    data_mode: String,
    code_search_url: String,
    context_generator_url: String,
    code_understanding_url: String,
    code_modifier_url: String,
    redis_url: String,
    openai_url: String,
    openai_api_key: String,
    openai_model: String,
}

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
            data_mode: env::var("DATA_MODE").unwrap_or_else(|_| "local".to_string()),
            code_search_url: env::var("CODE_SEARCH_URL")
                .unwrap_or_else(|_| "http://127.0.0.1:3000".to_string()),
            context_generator_url: env::var("CONTEXT_GENERATOR_URL")
                .unwrap_or_else(|_| "http://127.0.0.1:3000".to_string()),
            code_understanding_url: env::var("CODE_UNDERSTANDING_URL")
                .unwrap_or_else(|_| "http://127.0.0.1:3000".to_string()),
            code_modifier_url: env::var("CODE_MODIFIER_URL")
                .unwrap_or_else(|_| "http://127.0.0.1:3000".to_string()),
            redis_url: env::var("REDIS_URL")
                .unwrap_or_else(|_| "redis://127.0.0.1:6379".to_string()),
            openai_url: env::var("OPENAI_URL")
                .unwrap_or_else(|_| "https://api.openai.com".to_string()),
            openai_api_key: env::var("OPENAI_API_KEY")
                .unwrap_or_else(|_| "default_api_key".to_string()),
            openai_model: env::var("OPENAI_MODEL")
                .unwrap_or_else(|_| "gpt-4-1106-preview".to_string()),
        }
    }

    fn init_ai_gateway() -> Mutex<AIGatewayConfig> {
        // setup AI gateway
        let ai_gateway = match initialize_ai_gateway(None) {
            Ok(ai_gateway) => ai_gateway,
            Err(e) => {
                error!("Failed to initialize AI Gateway: {}", e);
                panic!("Failed to initialize AI Gateway: {}", e);
            }
        };

        Mutex::new(ai_gateway)
    }
}

static CONFIG: Lazy<Configuration> = Lazy::new(|| Configuration::load_from_env());
static AI_GATEWAY: Lazy<Mutex<AIGatewayConfig>> = Lazy::new(|| Configuration::init_ai_gateway());

// write a function test if the dependency services are up and running
async fn health_check(url: &str) -> bool {
    // do async request and await for the response
    let response = reqwest::get(url).await;
    response.is_ok()
}

#[tokio::main]
async fn main() -> Result<()> {
    env_logger::init();
    dotenv::dotenv().ok();

    info!("Loaded configuration: {:?}", *CONFIG);
    // health check code search url and code understanding url
    let code_search_url = &CONFIG.code_search_url;
    let code_understanding_url = &CONFIG.code_understanding_url;

    // call health only if the config data_mode is set to API
    info!("DATA MODE IS API, checking whether dependent services are up");
    if !health_check(code_search_url).await {
        panic!("Code search service is not available, please run the code search service first");
    }
    if !health_check(code_understanding_url).await {
        panic!("Code understanding service is not available, please run the code understanding service first");
    }
    info!("All dependent services are up!");

    // test redis connection
    set_redis_url(&CONFIG.redis_url); // Set redis url in the common package
    let _conn = establish_redis_connection().map_err(|e| {
        error!("Failed to establish Redis connection, check if Redis is running and is accessible: {:?}", e);
        panic!("Failed to establish Redis connection: {:?}", e);
    });

    // test if the AI gateway is initialized properly
    let _output = AI_GATEWAY
        .lock()
        .unwrap()
        .use_llm("Hello from the other side", None, None, None, true, false)
        
        .await
        .map_err(|e| {
            panic!("Failed to start AI Gateway: {:?}", e);
        });

    let coordinator_routes = routes::coordinator();
    warp::serve(coordinator_routes)
        .run(([0, 0, 0, 0], 3004))
        .await;
    info!("Started web server on http://localhost:3004");

    Ok(())
}
