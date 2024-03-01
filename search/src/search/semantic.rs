use anyhow::Result;
use std::{str, time::Duration};
use thiserror::Error;
use crate::search::semantic::SemanticError::QdrantInitializationError;

use crate::{
    parser::literal::Literal,
    search::payload::{Embedding, SymbolPayload},
};
use std::sync::Arc;

use ndarray::Axis;
use ort::tensor::OrtOwnedTensor;
use ort::value::Value;
use ort::{Environment, ExecutionProvider, GraphOptimizationLevel, LoggingLevel, SessionBuilder};
use qdrant_client::{
    prelude::{QdrantClient, QdrantClientConfig},
    qdrant::{
        r#match::MatchValue, with_payload_selector, with_vectors_selector, Condition,
        FieldCondition, Filter, Match, ScoredPoint, SearchPoints, WithPayloadSelector,
        WithVectorsSelector,
    },
};

use crate::Configuration;

pub struct Semantic {
    pub qdrant_collection_name: String,
    pub qdrant: QdrantClient,
    pub tokenizer: tokenizers::Tokenizer,
    pub session: ort::Session,
}

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

// fetch the qdrant client
pub async fn get_qdrant_client(config: &Configuration) -> Result<QdrantClient, SemanticError> {
    // if api key is not set, then initialize the qdrant client without the api key
    if config.qdrant_api_key.is_none() {
        let qdrant = QdrantClient::new(Some(
            QdrantClientConfig::from_url(&config.semantic_db_url)
                .with_timeout(Duration::from_secs(30))
                .with_connect_timeout(Duration::from_secs(30)),
        ))?;
        return Ok(qdrant);
    } 
    let qdrant = QdrantClient::new(Some(
        QdrantClientConfig::from_url(&config.semantic_db_url)
            .with_timeout(Duration::from_secs(30))
            .with_connect_timeout(Duration::from_secs(30))
            .with_api_key(config.qdrant_api_key.clone()),
    ))?;

    Ok(qdrant)
}

impl Semantic {
    pub async fn initialize(config: Configuration) -> Result<Self, SemanticError> {
        let qdrant = get_qdrant_client(&config).await;

        if qdrant.is_err() {
            return Err(QdrantInitializationError);
        }

        let qdrant = qdrant.unwrap();
        let environment = Arc::new(
            Environment::builder()
                .with_name("Encode")
                .with_log_level(LoggingLevel::Warning)
                .with_execution_providers([ExecutionProvider::CPU(Default::default())])
                .with_telemetry(false)
                .build()?,
        );

        let threads = if let Ok(v) = std::env::var("NUM_OMP_THREADS") {
            str::parse(&v).unwrap_or(1)
        } else {
            1
        };

        Ok(Self {
            qdrant: qdrant.into(),
            tokenizer: tokenizers::Tokenizer::from_file(config.tokenizer_path.as_str())
                .unwrap()
                .into(),
            session: SessionBuilder::new(&environment)?
                .with_optimization_level(GraphOptimizationLevel::Level3)?
                .with_intra_threads(threads)?
                .with_model_from_file(config.model_path)?
                .into(),
            qdrant_collection_name: config.symbol_collection_name,
        })
    }

    pub fn embed(&self, sequence: &str) -> anyhow::Result<Embedding> {
        let tokenizer_output = self.tokenizer.encode(sequence, true).unwrap();
        print!("tokenizer_output {:?}", tokenizer_output);

        let input_ids = tokenizer_output.get_ids();
        let attention_mask = tokenizer_output.get_attention_mask();
        let token_type_ids = tokenizer_output.get_type_ids();
        let length = input_ids.len();
        println!("embedding {} tokens {:?}", length, sequence);

        let inputs_ids_array = ndarray::Array::from_shape_vec(
            (1, length),
            input_ids.iter().map(|&x| x as i64).collect(),
        )?;

        let attention_mask_array = ndarray::Array::from_shape_vec(
            (1, length),
            attention_mask.iter().map(|&x| x as i64).collect(),
        )?;

        let token_type_ids_array = ndarray::Array::from_shape_vec(
            (1, length),
            token_type_ids.iter().map(|&x| x as i64).collect(),
        )?;

        let outputs = self.session.run(vec![
            Value::from_array(
                self.session.allocator(),
                &ndarray::CowArray::from(inputs_ids_array).into_dyn(),
            )
            .unwrap(),
            Value::from_array(
                self.session.allocator(),
                &ndarray::CowArray::from(attention_mask_array).into_dyn(),
            )
            .unwrap(),
            Value::from_array(
                self.session.allocator(),
                &ndarray::CowArray::from(token_type_ids_array).into_dyn(),
            )
            .unwrap(),
        ])?;

        let output_tensor: OrtOwnedTensor<f32, _> = outputs[0].try_extract().unwrap();
        let sequence_embedding = &*output_tensor.view();
        let pooled = sequence_embedding.mean_axis(Axis(1)).unwrap();
        Ok(pooled.to_owned().as_slice().unwrap().to_vec())
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
            collection_name: collection_name.to_owned().to_string(),
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

        // Print the serialized request
        println!("Search Request Debug: {:?}", search_request);

        let response = self.qdrant.search_points(search_request).await?;

        // iterate through the results and print the score and payload from each entry in the results
        let mut results = response.result.clone();
        results.sort_by(|a, b| b.score.partial_cmp(&a.score).unwrap());

        println!("---------xxxxxxxxxxxxxxx----------------");
        println!("{:?}", results.clone());

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
