use dotenv::dotenv;
use lazy_static::lazy_static;
use std::env;
use std::sync::RwLock;

use common::docker::is_running_in_docker;

#[derive(Debug, Default)]
pub struct Config {
    pub qdrant_url: String,
    pub quickwit_url: String,
    pub yaml_config_path: String,
    pub model_path: String,
}

lazy_static! {
    static ref GLOBAL_CONFIG: RwLock<Config> = RwLock::new(Config::default());
}

pub fn initialize_config(env_file: Option<String>) {
    if let Some(file) = env_file {
        dotenv::from_filename(file).expect("Failed to load environment file");
    } else {
        dotenv().expect("Failed to load environment file");
    }

    let config = Config {
        qdrant_url: env::var("SEMANTIC_DB_URL")
            .expect("`QDRANT_URL` environment variable must be set"),
        quickwit_url: env::var("QUICKWIT_DB_URL")
            .expect("`QUICKWIT_URL` environment variable must be set"),
        yaml_config_path: env::var("QUICKWIT_YAML_CONFIG_PATH")
            .expect("`YAML_CONFIG_PATH` environment variable must be set"),
        model_path: env::var("MODEL_DIR").expect("`MODEL_PATH` environment variable must be set"),
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
