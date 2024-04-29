use crate::{config::Configuration, search::semantic::Semantic}; 
use reqwest::Client;
use thiserror::Error;
use log::{error, info};

#[derive(Error, Debug)]
pub enum SemanticError {
    /// Represents failure to initialize Qdrant client
    #[error("Qdrant initialization failed. Is Qdrant running on `qdrant-url`?")]
    QdrantInitializationError,

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

pub async fn init_db() -> Result<DbConnect, anyhow::Error> {
    let http_client = reqwest::Client::new();

    let semantic = Semantic::initialize().await;
    match semantic {
        Ok(semantic) => {
            info!("Semantic search initialized");
            Ok(DbConnect {
                semantic,
                http_client,
            })
        }
        Err(err) => {
            info!("Failed to initialize semantic search: {}", err);
            Err(err.into())
        }
    }
}
