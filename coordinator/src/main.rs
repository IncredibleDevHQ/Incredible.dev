use anyhow::Result;
use common::ai_util::call_llm;
use common::docker::is_running_in_docker;
use common::task_graph::redis::establish_redis_connection;
use configuration::Configuration;
use std::sync::{RwLock, RwLockWriteGuard};
use std::thread::sleep;
use std::time::Duration;
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
    RwLock::new(Configuration::default())
});

/// Performs a health check on a given URL with a retry if the first attempt fails.
///
/// # Arguments
/// * `url` - The URL to check for service availability.
///
/// # Returns
/// Returns `true` if the service is up and running, otherwise `false`.
async fn health_check(url: &str) -> bool {
    let max_attempts = 2; // Total attempts: 1 initial + 1 retry
    let retry_delay = Duration::from_secs(5); // Delay 5 seconds before retry

    for attempt in 1..=max_attempts {
        log::debug!("Attempt {} to check health of {}", attempt, url);
        match reqwest::get(url).await {
            Ok(response) => {
                if response.status().is_success() {
                    log::info!("Service at {} is up and running.", url);
                    return true;
                } else {
                    log::warn!(
                        "Service at {} returned non-success status: {}",
                        url,
                        response.status()
                    );
                }
            }
            Err(e) => {
                log::error!("Failed to reach service at {}: {}", url, e);
            }
        }

        if attempt < max_attempts {
            log::debug!(
                "Waiting for {} seconds before retrying...",
                retry_delay.as_secs()
            );
            sleep(retry_delay); // Wait for some time before the next retry
        }
    }

    log::warn!(
        "Service at {} is not responding after {} attempts.",
        url,
        max_attempts
    );
    false // Return false if all attempts fail
}

pub fn load_from_env(env_file: Option<String>) -> Configuration {
    // Check if running inside Docker first
    if is_running_in_docker() {
        log::debug!("Running coorindator Docker container");
    }

    // load the .env file from the specified path if provided, otherwise load the default .env file
    if let Some(env_path) = env_file {
        dotenv::from_filename(&env_path)
            .expect(format!("Failed to load environment variables from {}", env_path).as_str());
        info!("Loaded environment variables from {}", env_path);
    } else {
        dotenv::dotenv().expect("Failed to load environment variables from .env file");
    }

    let ai_gateway_config_path = env::var("AI_GATEWAY_CONFIG_PATH")
        .expect("AI_GATEWAY_CONFIG_PATH environment variable is not set");

    let ai_gateway_config = fs::read_to_string(&ai_gateway_config_path).expect(&format!(
        "Failed to read AI Gateway config file at: {}",
        ai_gateway_config_path
    ));

    info!("AI Gateway configuration loaded successfully.");

    Configuration {
        code_search_url: env::var("CODE_SEARCH_URL")
            .expect("CODE_SEARCH_URL environment variable is not set"),
        code_understanding_url: env::var("CODE_UNDERSTANDING_URL")
            .expect("CODE_UNDERSTANDING_URL environment variable is not set"),
        redis_url: env::var("REDIS_URL").expect("REDIS_URL environment variable is not set"),
        ai_gateway_config,
    }
}

#[tokio::main]
async fn main() -> Result<()> {
    env_logger::init();

    // Parse command line arguments
    let args: Vec<String> = env::args().collect();
    let mut env_file: Option<String> = None;

    if args.len() > 1 {
        for i in 1..args.len() {
            if args[i] == "--env-file" {
                if i + 1 < args.len() {
                    env_file = Some(args[i + 1].clone());
                } else {
                    eprintln!("--env-file requires a value");
                    std::process::exit(1);
                }
            }
        }
    }

    // Load configuration
    let config = load_from_env(env_file);
    {
        let mut global_config: RwLockWriteGuard<Configuration> =
            CONFIG.write().expect("Failed to acquire write lock");
        *global_config = config;
    }

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
