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
}

impl Config {
    pub fn new() -> Result<Self, anyhow::Error> {
        dotenv::dotenv().ok(); // This attempts to load the .env file, but ignores any error if the file is not found

        // TODO: For Prod also look for QDRANT API KEY.
        // Directly use `?` to propagate the error if the environment variable is not set.
        let semantic_url = std::env::var("SEMANTIC_URL")?;
        let qdrant_api_key = std::env::var("QDRANT_API_KEY").ok();
        let tokenizer_path = std::env::var("TOKENIZER_PATH")?;
        let model_path = std::env::var("MODEL_PATH")?;
        let openai_key = std::env::var("OPENAI_KEY")?;
        let openai_url = std::env::var("OPENAI_URL")?;
        let openai_model = std::env::var("OPENAI_MODEL")?;
        let quickwit_url = std::env::var("QUICKWIT_URL")?;
        let semantic_collection_name = std::env::var("SEMANTIC_COLLECTION_NAME")?;
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
        })
    }
}
