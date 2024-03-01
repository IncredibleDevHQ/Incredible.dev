pub struct Config {
    pub repo_name: String,
    pub semantic_url: String,
    pub tokenizer_path: String,
    pub model_path: String,
    pub openai_key: String,
    pub openai_url: String,
    pub openai_model: String,
    pub quickwit_url: String,
    pub semantic_collection_name: String,
}

impl Config {
    pub fn new() -> Result<Self, String> {
        dotenv::dotenv().ok(); // This attempts to load the .env file, but ignores any error if the file is not found

        let repo_name =
            std::env::var("REPO_NAME").map_err(|_| "REPO_NAME environment variable not set")?;
        let semantic_url = std::env::var("SEMANTIC_URL")
            .map_err(|_| "SEMANTIC_URL environment variable not set")?;
        let tokenizer_path = std::env::var("TOKENIZER_PATH")
            .map_err(|_| "TOKENIZER_PATH environment variable not set")?;
        let model_path =
            std::env::var("MODEL_PATH").map_err(|_| "MODEL_PATH environment variable not set")?;
        let openai_key =
            std::env::var("OPENAI_KEY").map_err(|_| "OPENAI_KEY environment variable not set")?;
        let openai_url =
            std::env::var("OPENAI_URL").map_err(|_| "OPENAI_URL environment variable not set")?;
        let openai_model = std::env::var("OPENAI_MODEL")
            .map_err(|_| "OPENAI_MODEL environment variable not set")?;
        let quickwit_url = std::env::var("QUICKWIT_URL")
            .map_err(|_| "QUICKWIT_URL environment variable not set")?;
        let semantic_collection_name = std::env::var("SEMANTIC_COLLECTION_NAME")
            .map_err(|_| "SEMANTIC_COLLECTION_NAME environment variable not set")?;

        Ok(Config {
            repo_name,
            semantic_url,
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
