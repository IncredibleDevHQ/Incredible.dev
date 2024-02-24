pub struct Config {
    pub semantic_url: String,
    pub tokenizer_path: String,
    pub model_path: String,
    pub openai_key: String,
    pub openai_url: String,
    pub openai_model: String,
}

impl Config {
    pub fn new() -> Result<Self, String> {
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

        Ok(Config {
            semantic_url,
            tokenizer_path,
            model_path,
            openai_key,
            openai_url,
            openai_model,
        })
    }
}

// create new configuration.
// let configuration = Configuration {
//     repo_name: "bloop-ai".to_string(),
//     semantic_collection_name: "documents".to_string(),
//     semantic_url: "http://localhost:6334".to_string(),
//     tokenizer_path: "./model/tokenizer.json".to_string(),
//     model_path: "./model/model.onnx".to_string(),
//     openai_key: "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".to_string(),
//     openai_url: "https://api.openai.com".to_string(),
//     openai_model: "gpt-4".to_string(),
// };
