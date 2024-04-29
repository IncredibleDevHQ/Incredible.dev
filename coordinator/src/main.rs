use anyhow::Result;
use common::ai_util::call_llm;
use common::docker::is_running_in_docker;
use common::task_graph::redis::establish_redis_connection;
use configuration::Configuration;
use std::sync::RwLock;
use std::{env, fs, process};

use log::{error, info};
use once_cell::sync::Lazy;

mod code_understanding;
mod configuration;
mod controller;
mod llm_ops;
mod models;
mod routes;
mod utility;

use core::result::Result::Ok;

use crate::configuration::{
    get_ai_gateway_config, get_code_search_url, get_code_understanding_url, get_redis_url,
};

// global configuration while RwLock is used to ensure thread safety
// Rwlock makes reads cheap, which is important because we will be reading the configuration a lot, and never mutate it after it is set.

static CONFIG: Lazy<RwLock<Configuration>> = Lazy::new(|| {
    // Directly load the configuration when initializing CONFIG.
    RwLock::new(load_from_env())
});

// write a function test if the dependency services are up and running
async fn health_check(url: &str) -> bool {
    // do async request and await for the response
    let response = reqwest::get(url).await;
    response.is_ok()
}

pub fn load_from_env() -> Configuration {
    // Check if running inside Docker first
    if !is_running_in_docker() {
        // Try to load .env file if not in Docker
        if dotenv::dotenv().is_err() {
            error!("No .env file found and not running in Docker, application will exit.");
            process::exit(1);
        }
    }

    let ai_gateway_config_path = env::var("AI_GATEWAY_CONFIG_PATH")
        .expect("AI_GATEWAY_CONFIG_PATH environment variable is not set");

    let ai_gateway_config = fs::read_to_string(&ai_gateway_config_path)
        .expect(&format!("Failed to read AI Gateway config file at: {}", ai_gateway_config_path));

    info!("Environment and AI Gateway configuration loaded successfully.");

    Configuration {
        code_search_url: env::var("CODE_SEARCH_URL").unwrap_or_else(|_| "http://127.0.0.1:3003".to_string()),
        code_understanding_url: env::var("CODE_UNDERSTANDING_URL").unwrap_or_else(|_| "http://127.0.0.1:3002".to_string()),
        redis_url: env::var("REDIS_URL").unwrap_or_else(|_| "redis://127.0.0.1:6379".to_string()),
        ai_gateway_config,
    }
}
#[tokio::main]
async fn main() -> Result<()> {
    env_logger::init();

    info!("Testing AI Gateway");
    let test_msg = "What LLM model are you?".to_string();
    // Test if the AI gateway is initialized properly, debug log the error and end the program
    let llm_test_output = call_llm(&get_ai_gateway_config(), Some(test_msg), None, None)
        .await
        .map_err(|e| {
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
