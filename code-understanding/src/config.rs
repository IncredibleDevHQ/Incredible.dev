use std::{env, fs};
use log::info;
#[derive(Clone, Debug)]
pub struct Config {
    pub semantic_url: String,
    pub qdrant_api_key: Option<String>,
    pub tokenizer_path: String,
    pub model_path: String,
    pub openai_key: String,
    pub openai_url: String,
    pub openai_model: String,
    pub quickwit_url: String,
    pub semantic_collection_name: String,
    pub search_server_url: String,
    // String containing the yaml configuration of the AI Gateway
    pub ai_gateway_config: String,
}

pub async fn load_from_env() -> Result<Config, anyhow::Error> {
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

    info!("Env configuration along with AI Gateway configuration loaded successfully.");

    // Directly use `?` to propagate the error if the environment variable is not set for OPENAI_KEY
    let openai_key =
        std::env::var("OPENAI_KEY").expect("OPENAI_KEY environment variable is not set");

    // Default values are provided using `unwrap_or_else` for other variables
    let semantic_url =
        env::var("SEMANTIC_URL").unwrap_or_else(|_| "http://localhost:6334".to_string());
    let qdrant_api_key = env::var("QDRANT_API_KEY").ok(); // It's optional
    let tokenizer_path =
        env::var("TOKENIZER_PATH").unwrap_or_else(|_| "./model/tokenizer.json".to_string());
    let model_path = env::var("MODEL_PATH").unwrap_or_else(|_| "./model/model.onnx".to_string());
    let openai_url =
        env::var("OPENAI_URL").unwrap_or_else(|_| "https://api.openai.com".to_string());
    let openai_model = env::var("OPENAI_MODEL").unwrap_or_else(|_| "gpt-4".to_string());
    let quickwit_url =
        env::var("QUICKWIT_URL").unwrap_or_else(|_| "http://localhost:7280".to_string());
    let semantic_collection_name =
        env::var("SEMANTIC_COLLECTION_NAME").unwrap_or_else(|_| "documents".to_string());
    let search_server_url =
        env::var("SEARCH_SERVER_URL").unwrap_or_else(|_| "http://localhost:3003".to_string());

    Ok(Config {
        semantic_url,
        qdrant_api_key,
        tokenizer_path,
        model_path,
        openai_key,
        openai_url,
        openai_model,
        quickwit_url,
        semantic_collection_name,
        search_server_url,
        ai_gateway_config,
    })
}
