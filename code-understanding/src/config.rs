use log::info;
use std::{env, fs};

use crate::CONFIG;
#[derive(Clone, Debug)]
pub struct Config {
    pub qdrant_api_key: Option<String>,
    pub semantic_url: String,
    pub quickwit_url: String,
    pub search_server_url: String,
    pub redis_url: String,
    // String containing the yaml configuration of the AI Gateway
    pub ai_gateway_config: String,
}

pub fn load_from_env() -> Config {
    dotenv::dotenv().unwrap();

    // Attempt to retrieve AI gateway configuration path from environment
    let ai_gateway_config_path = env::var("AI_GATEWAY_CONFIG_PATH")
        .expect("AI_GATEWAY_CONFIG_PATH environment variable is not set");

    // Read the configuration file content
    let ai_gateway_config = fs::read_to_string(&ai_gateway_config_path).expect(&format!(
        "Failed to read AI Gateway config file at: {}",
        ai_gateway_config_path
    ));

    info!("Env configuration along with AI Gateway configuration loaded successfully.");

    let qdrant_api_key = env::var("QDRANT_API_KEY").ok();
    // Default values are provided using `unwrap_or_else` for other variables
    let semantic_url =
        env::var("SEMANTIC_URL").unwrap_or_else(|_| "http://localhost:6334".to_string());
    let quickwit_url =
        env::var("QUICKWIT_URL").unwrap_or_else(|_| "http://localhost:7280".to_string());
    let search_server_url =
        env::var("SEARCH_SERVER_URL").unwrap_or_else(|_| "http://localhost:3003".to_string());
    let redis_url = env::var("REDIS_URL").unwrap_or_else(|_| "redis://localhost:6379".to_string());

    Config {
        qdrant_api_key,
        semantic_url,
        quickwit_url,
        search_server_url,
        redis_url,
        ai_gateway_config,
    }
}

pub fn get_semantic_url() -> String {
    CONFIG.read().unwrap().semantic_url.clone()
}

pub fn get_quickwit_url() -> String {
    CONFIG.read().unwrap().quickwit_url.clone()
}

pub fn get_search_server_url() -> String {
    CONFIG.read().unwrap().search_server_url.clone()
}

// New getter for ai_gateway_config
pub fn get_ai_gateway_config() -> String {
    CONFIG.read().unwrap().ai_gateway_config.clone()
}

pub fn get_redis_url() -> String {
    CONFIG.read().unwrap().redis_url.clone()
}

pub fn clone_config() -> Config {
    CONFIG.read().unwrap().clone()
}
