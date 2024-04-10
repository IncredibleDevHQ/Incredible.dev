use ai_gateway::config::AIGatewayConfig;
use anyhow::Result;
use common::ast::debug;
use common::task_graph::redis::establish_redis_connection;
use configuration::{get_ai_gateway_config, Configuration};
use std::sync::RwLock;
use std::{env, fs};

use log::{debug, error, info};
use once_cell::sync::Lazy;

mod configuration;
mod controller;
mod llm_ops;
mod models;
mod routes;
mod utility;

use core::result::Result::Ok;

use crate::configuration::{get_code_search_url, get_code_understanding_url, get_redis_url};

static CONFIG: Lazy<RwLock<Option<Configuration>>> = Lazy::new(|| RwLock::new(None));
// write a function test if the dependency services are up and running
async fn health_check(url: &str) -> bool {
    // do async request and await for the response
    let response = reqwest::get(url).await;
    response.is_ok()
}

async fn test_ai_gateway() -> Result<String> {
    let config = get_ai_gateway_config();
    debug!("AI Gateway config from file: {}", config);
    let mut ai_gateway_config = AIGatewayConfig::from_yaml(&config)?;
    debug!("AI Gateway config from gateway lib: {:?}", ai_gateway_config);
    let result = ai_gateway_config
        .use_llm("Can indians code?", None, None, true, false)
        .await?;

    Ok(result)
}

pub async fn load_from_env() -> Configuration {
    let environment = env::var("RUST_ENV").unwrap_or_else(|_| "development".to_string());
    let env_file = format!(".env.{}", environment);

    info!("Loading configurations from {}", env_file);
    dotenv::from_filename(env_file).expect("Failed to load .env file");

    // Attempt to retrieve AI gateway configuration path from environment
    let ai_gateway_config_path = env::var("AI_GATEWAY_CONFIG_PATH")
        .expect("AI_GATEWAY_CONFIG_PATH environment variable is not set");

    // Read the configuration file content
    let ai_gateway_config = fs::read_to_string(&ai_gateway_config_path).expect(&format!(
        "Failed to read AI Gateway config file at: {}",
        ai_gateway_config_path
    ));

    Configuration {
        environment: env::var("ENVIRONMENT").unwrap_or_else(|_| environment),
        code_search_url: env::var("CODE_SEARCH_URL")
            .unwrap_or_else(|_| "http://127.0.0.1:3000".to_string()),
        context_generator_url: env::var("CONTEXT_GENERATOR_URL")
            .unwrap_or_else(|_| "http://127.0.0.1:3000".to_string()),
        code_understanding_url: env::var("CODE_UNDERSTANDING_URL")
            .unwrap_or_else(|_| "http://127.0.0.1:3000".to_string()),
        code_modifier_url: env::var("CODE_MODIFIER_URL")
            .unwrap_or_else(|_| "http://127.0.0.1:3000".to_string()),
        redis_url: env::var("REDIS_URL").unwrap_or_else(|_| "redis://127.0.0.1:6379".to_string()),
        openai_url: env::var("OPENAI_URL").unwrap_or_else(|_| "https://api.openai.com".to_string()),
        openai_api_key: env::var("OPENAI_API_KEY")
            .unwrap_or_else(|_| "default_api_key".to_string()),
        openai_model: env::var("OPENAI_MODEL").unwrap_or_else(|_| "gpt-4-1106-preview".to_string()),
        ai_gateway_config,
    }
}

#[tokio::main]
async fn main() -> Result<()> {
    env_logger::init();
    dotenv::dotenv().ok();

    // Load the configuration from the environments
    // Load the configuration from the environments
    let config = load_from_env().await;

    // Scope for the write lock so it gets released as soon as the configuration is set
    {
        let mut config_lock = CONFIG.write().unwrap();
        *config_lock = Some(config.clone());
    } // config_lock goes out of scope here, releasing the write lock

    info!("Loaded configuration");
    debug!("Config data: {:?}", &config);

    info!("Testing AI Gateway");
    // Test if the AI gateway is initialized properly, debug log the error and end the program
    let llm_test_output = test_ai_gateway().await.map_err(|e| {
        error!("Failed to start AI Gateway: {:?}", e);
        panic!("AI Gateway initialization failed");
    });

    info!("Successful LLM response: {:?}", llm_test_output.unwrap());
    // health check code search url and code understanding url
    let code_search_url = get_code_search_url();
    let code_understanding_url = get_code_understanding_url();

    if !health_check(&code_search_url).await {
        panic!("Code search service is not available, please run the code search service first");
    }
    if !health_check(&code_understanding_url).await {
        panic!("Code understanding service is not available, please run the code understanding service first");
    }
    info!("All dependent services are up!");

    // test redis connection
    let _conn = establish_redis_connection(&get_redis_url()).map_err(|e| {
        error!("Failed to establish Redis connection, check if Redis is running and is accessible: {:?}", e);
        panic!("Failed to establish Redis connection: {:?}", e);
    });

    let coordinator_routes = routes::coordinator();
    warp::serve(coordinator_routes)
        .run(([0, 0, 0, 0], 3004))
        .await;
    info!("Started web server on http://localhost:3004");

    Ok(())
}
