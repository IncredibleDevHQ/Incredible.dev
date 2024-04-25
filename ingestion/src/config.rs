use std::sync::RwLock;
use lazy_static::lazy_static;

#[derive(Debug)]
pub struct Config {
    pub qdrant_url: String,
    pub quickwit_url: String,
    pub yaml_config_path: String,
    pub model_path: String,
}

lazy_static! {
    static ref GLOBAL_CONFIG: RwLock<Config> = RwLock::new(Config {
        qdrant_url: String::new(),
        quickwit_url: String::new(),
        yaml_config_path: String::new(),
        model_path: String::new(),
    });
}

use std::env;
use dotenv::dotenv;

pub fn initialize_config() {
    dotenv().ok(); // Load environment variables from .env file if available

    let config = Config {
        qdrant_url: env::var("QDRANT_URL").unwrap_or_else(|_| "http://localhost:6334".to_string()),
        quickwit_url: env::var("QUICKWIT_URL").unwrap_or_else(|_| "http://localhost:7280".to_string()),
        yaml_config_path: env::var("YAML_CONFIG_PATH").unwrap(),
        model_path: env::var("MODEL_PATH").unwrap(),

    };

    let mut global_config = GLOBAL_CONFIG.write().expect("Failed to acquire write lock");
    *global_config = config;
}

pub fn get_qdrant_url() -> String {
    GLOBAL_CONFIG.read().unwrap().qdrant_url.clone()
}

pub fn get_quickwit_url() -> String {
    GLOBAL_CONFIG.read().unwrap().quickwit_url.clone()
}

pub fn get_yaml_config_path() -> String {
    GLOBAL_CONFIG.read().unwrap().yaml_config_path.clone()
}

pub fn get_model_path() -> String {
    GLOBAL_CONFIG.read().unwrap().model_path.clone()
}
