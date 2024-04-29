use crate::{config::{get_model_path, get_qdrant_api_key, get_semantic_db_url, get_symbol_collection_name}, search::semantic::SemanticError::QdrantInitializationError};
use anyhow::Result;
use common::hasher::generate_qdrant_index_name;
use std::{str, time::Duration};
use thiserror::Error;

use crate::{
    parser::literal::Literal,
    search::payload::{Embedding, SymbolPayload},
};

use qdrant_client::{
    prelude::{QdrantClient, QdrantClientConfig},
    qdrant::{
        r#match::MatchValue, with_payload_selector, with_vectors_selector, Condition,
        FieldCondition, Filter, Match, ScoredPoint, SearchPoints, WithPayloadSelector,
        WithVectorsSelector,
    },
};

pub struct Semantic {
    pub qdrant_collection_name: String,
    pub qdrant: QdrantClient,
    tokenizer_onnx: common::tokenizer_onnx::TokenizerOnnx,
}

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

// fetch the qdrant client
pub async fn get_qdrant_client() -> Result<QdrantClient, SemanticError> {
    // if api key is not set, then initialize the qdrant client without the api key
    if get_qdrant_api_key().is_none() {
        let qdrant = QdrantClient::new(Some(
            QdrantClientConfig::from_url(&get_semantic_db_url())
                .with_timeout(Duration::from_secs(30))
                .with_connect_timeout(Duration::from_secs(30)),
        ))?;
        return Ok(qdrant);
    }
    let qdrant = QdrantClient::new(Some(
        QdrantClientConfig::from_url(&get_semantic_db_url())
            .with_timeout(Duration::from_secs(30))
            .with_connect_timeout(Duration::from_secs(30))
            .with_api_key(get_qdrant_api_key()),
    ))?;

    Ok(qdrant)
}

impl Semantic {
    pub async fn initialize() -> Result<Self, SemanticError> {
        let qdrant = get_qdrant_client().await;

        if qdrant.is_err() {
            return Err(QdrantInitializationError);
        }
        let qdrant = qdrant.unwrap();
        Ok(Self {
            qdrant: qdrant.into(),
            tokenizer_onnx: common::tokenizer_onnx::TokenizerOnnx::new(&get_model_path())?,
            qdrant_collection_name: get_symbol_collection_name(), 
        })
    }

    pub fn embed(&self, sequence: &str) -> anyhow::Result<Embedding> {
        self.tokenizer_onnx.get_embedding(sequence)
    }

    // function to perform semantic search on the symbols.
    pub async fn search_symbol<'a>(
        &self,
        parsed_query: Literal<'a>,
        limit: u64,
        offset: u64,
        threshold: f32,
        retrieve_more: bool,
        repo_name: &String,
    ) -> anyhow::Result<Vec<SymbolPayload>> {
        let query = parsed_query.as_plain().unwrap();
        let vector = self.embed(&query)?;

        // TODO: Remove the need for `retrieve_more`. It's here because:
        // In /q `limit` is the maximum number of results returned (the actual number will often be lower due to deduplication)
        // In /answer we want to retrieve `limit` results exactly
        let results = self
            .search_with(
                self.qdrant_collection_name.as_str(),
                vector.clone(),
                if retrieve_more { limit * 2 } else { limit }, // Retrieve double `limit` and deduplicate
                offset,
                threshold,
                repo_name,
            )
            .await
            .map(|raw| {
                raw.into_iter()
                    .map(SymbolPayload::from_qdrant)
                    .collect::<Vec<_>>()
            })?;
        Ok(results)
    }

    pub async fn search_with<'a>(
        &self,
        collection_name: &str,
        vector: Embedding,
        limit: u64,
        offset: u64,
        threshold: f32,
        repo_name: &String,
    ) -> anyhow::Result<Vec<ScoredPoint>> {
        let mut conditions: Vec<Condition> = Vec::new();

        conditions.push(make_kv_keyword_filter("repo_name", repo_name).into());

        let search_request = &SearchPoints {
            limit,
            vector,
            collection_name: generate_qdrant_index_name(repo_name),
            offset: Some(offset),
            score_threshold: Some(threshold),
            with_payload: Some(WithPayloadSelector {
                selector_options: Some(with_payload_selector::SelectorOptions::Enable(true)),
            }),
            filter: Some(Filter {
                must: conditions,
                ..Default::default()
            }),
            with_vectors: Some(WithVectorsSelector {
                selector_options: Some(with_vectors_selector::SelectorOptions::Enable(true)),
            }),
            ..Default::default()
        };

        let response = self.qdrant.search_points(search_request).await?;

        // iterate through the results and print the score and payload from each entry in the results
        let mut results = response.result.clone();
        results.sort_by(|a, b| b.score.partial_cmp(&a.score).unwrap());

        let _acc = results
            .iter()
            .flat_map(|result| {
                let payload = result.payload.clone();
                let score = result.score;

                Some((payload, score))
            })
            .map(|(payload, score)| {
                println!("payload: {:?}", payload);
                println!("score: {:?}", score);
            })
            .collect::<Vec<_>>();

        Ok(response.result)
    }
}

// Exact match filter
pub(crate) fn make_kv_keyword_filter(key: &str, value: &str) -> FieldCondition {
    let key = key.to_owned();
    let value = value.to_owned();
    FieldCondition {
        key,
        r#match: Some(Match {
            match_value: MatchValue::Keyword(value).into(),
        }),
        ..Default::default()
    }
}
