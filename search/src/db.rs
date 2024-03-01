use crate::{search::semantic::Semantic, Configuration};
use reqwest::Client;
use thiserror::Error;

#[derive(Error, Debug)]
pub enum SemanticError {
    /// Represents failure to initialize Qdrant client
    #[error("Qdrant initialization failed. Is Qdrant running on `qdrant-url`?")]
    QdrantInitializationError,

    #[error("ONNX runtime error")]
    OnnxRuntimeError {
        #[from]
        error: ort::OrtError,
    },

    #[error("semantic error")]
    Anyhow {
        #[from]
        error: anyhow::Error,
    },
}

pub struct DbConnect {
    pub semantic: Semantic,
    pub http_client: Client,
}

pub async fn init_db(config: Configuration) -> Result<DbConnect, anyhow::Error> {
    let http_client = reqwest::Client::new();

    let semantic = Semantic::initialize(config).await;
    match semantic {
        Ok(semantic) => {
            println!("Semantic search initialized");
            Ok(DbConnect {
                semantic,
                http_client,
            })
        }
        Err(err) => {
            println!("Failed to initialize semantic search: {}", err);
            Err(err.into())
        }
    }
}
