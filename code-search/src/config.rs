
use anyhow::Context;
use std::sync::RwLock;
use lazy_static::lazy_static;
use std::env;

use crate::db;
use common::docker::is_running_in_docker;


#[derive(Debug, Clone)]
pub struct Configuration {
    symbol_collection_name: String,
    semantic_db_url: String,
    quikwit_db_url: String,
    model_path: String,
    qdrant_api_key: Option<String>,
}

struct AppState {
    db_connection: db::DbConnect,
}

// Create a global instance of the configuration
lazy_static! {
    static ref GLOBAL_CONFIG: RwLock<Configuration> = RwLock::new(Configuration {
        symbol_collection_name: String::new(),
        semantic_db_url: String::new(),
        quikwit_db_url: String::new(),
        model_path: String::new(),
        qdrant_api_key: None,
    });
}

// Function to load the configuration from the environment
pub async fn initialize_config() -> anyhow::Result<AppState> {
    if !is_running_in_docker() {
        dotenv::dotenv().ok(); // Load environment variables from .env file if available
    }

    let config = Configuration {
        symbol_collection_name: "default_symbol_collection".to_string(), // Set a default or pull from env
        semantic_db_url: env::var("SEMANTIC_DB_URL").context("SEMANTIC_DB_URL must be set")?,
        quikwit_db_url: env::var("QUICKWIT_DB_URL").context("QUICKWIT_DB_URL must be set")?,
        model_path: env::var("MODEL_PATH").context("MODEL_PATH must be set")?,
        qdrant_api_key: env::var("QDRANT_CLOUD_API_KEY").ok(), // Optional, hence `ok()`
    };

    let mut global_config = GLOBAL_CONFIG.write().expect("Failed to acquire write lock");
    *global_config = config.clone();

    let db_connection = db::init_db(config).await?;

    Ok(AppState {
        db_connection,
    })
}

 // Getter for the symbol collection name
 pub fn symbol_collection_name() -> String {
    GLOBAL_CONFIG.read().unwrap().symbol_collection_name.clone()
}

// Getter for the Semantic DB URL
pub fn semantic_db_url() -> String {
    GLOBAL_CONFIG.read().unwrap().semantic_db_url.clone()
}

// Getter for the QuickWit DB URL
pub fn quickwit_db_url() -> String {
    GLOBAL_CONFIG.read().unwrap().quickwit_db_url.clone()
}

// Getter for the model path
pub fn model_path() -> String {
    GLOBAL_CONFIG.read().unwrap().model_path.clone()
}

// Getter for the Qdrant API Key
pub fn qdrant_api_key() -> Option<String> {
    GLOBAL_CONFIG.read().unwrap().qdrant_api_key.clone()
}