use thiserror::Error;
use tracing::log::debug;
// import hashset from collections
use std::{
    collections::HashMap, 
    str,
};
// import anyhow from anyhow
use crate::config::{get_model_path, Config};
use crate::search::payload::{Embedding, Payload};
use anyhow::Result;
use log::{error, info};
use qdrant_client::{
    prelude::QdrantClient,
    qdrant::{r#match::MatchValue, FieldCondition, Match},
};

pub struct Semantic {
    pub qdrant_collection_name: String,
    pub qdrant: QdrantClient,
    pub tokenize_onnx: common::tokenizer_onnx::TokenizerOnnx,
}

#[derive(Error, Debug)]
pub enum SemanticError {
    /// Represents failure to initialize Qdrant client
    #[allow(unused)]
    #[error("Qdrant initialization failed. Is Qdrant running on `qdrant-url`?")]
    QdrantInitializationError,

    #[error("semantic error")]
    Anyhow {
        #[from]
        error: anyhow::Error,
    },
}

impl Semantic {
    // Define an asynchronous function 'initialize' that takes a reference to a Config object and returns a Result.
    // This function initializes the struct it belongs to.
    pub async fn initialize(config: &Config) -> Result<Self, SemanticError> {
        // Retrieve the Qdrant URL from the config object. We use a reference here to avoid ownership issues.
        let qdrant_url = &config.semantic_url;

        // Start building the Qdrant client with the URL.
        let mut qdrant_client_builder = QdrantClient::from_url(qdrant_url);

        // Check if the qdrant_api_key is present in the config. If it is, add it to the client builder.
        if let Some(ref key) = config.qdrant_api_key {
            info!("Using Qdrant API key. Using Qdrant with authentication.");
            qdrant_client_builder = qdrant_client_builder.with_api_key(key.as_str());
        } else {
            info!("No Qdrant API key found. Using Qdrant without authentication.")
        }

        // Finalize building the Qdrant client. If this fails, the error will be propagated by `?`.
        let qdrant = qdrant_client_builder.build()?;

        // Construct and return the new instance, initializing each field.
        Ok(Self {
            qdrant: qdrant.into(),
            tokenize_onnx: common::tokenizer_onnx::TokenizerOnnx::new(&get_model_path())?,
            qdrant_collection_name: common::service_interaction::DOCUMENT_COLLECTION_NAME.to_string(), 
        })
    }

    pub fn embed(&self, sequence: &str) -> anyhow::Result<Embedding> {
        self.tokenize_onnx.get_embedding(sequence)
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

pub fn deduplicate_snippets(
    mut all_snippets: Vec<Payload>,
    query_embedding: Embedding,
    output_count: u64,
) -> Vec<Payload> {
    all_snippets = filter_overlapping_snippets(all_snippets);

    let idxs = {
        let lambda = 0.5;
        let k = output_count; // number of snippets
        let embeddings = all_snippets
            .iter()
            .map(|s| s.embedding.as_deref().unwrap())
            .collect::<Vec<_>>();
        let languages = all_snippets
            .iter()
            .map(|s| s.lang.as_ref())
            .collect::<Vec<_>>();
        let paths = all_snippets
            .iter()
            .map(|s| s.relative_path.as_ref())
            .collect::<Vec<_>>();
        deduplicate_with_mmr(
            &query_embedding,
            &embeddings,
            &languages,
            &paths,
            lambda,
            k as usize,
        )
    };

    log::debug!("preserved idxs after MMR are {:?}", idxs);

    all_snippets
        .drain(..)
        .enumerate()
        .filter_map(|(ref i, payload)| {
            if idxs.contains(i) {
                Some(payload)
            } else {
                None
            }
        })
        .collect()
}

fn filter_overlapping_snippets(mut snippets: Vec<Payload>) -> Vec<Payload> {
    snippets.sort_by(|a, b| {
        a.relative_path
            .cmp(&b.relative_path)
            .then(a.start_line.cmp(&b.start_line))
    });

    snippets = snippets
        .into_iter()
        .fold(Vec::<Payload>::new(), |mut deduped_snippets, snippet| {
            if let Some(prev) = deduped_snippets.last_mut() {
                if prev.relative_path == snippet.relative_path
                    && prev.end_line >= snippet.start_line
                {
                    debug!(
                        "Filtering overlapping snippets. End: {:?} - Start: {:?} from {:?}",
                        prev.end_line, snippet.start_line, prev.relative_path
                    );
                    return deduped_snippets;
                }
            }
            deduped_snippets.push(snippet);
            deduped_snippets
        });

    snippets.sort_by(|a, b| b.score.partial_cmp(&a.score).unwrap());
    snippets
}

// returns a list of indices to preserve from `snippets`
//
// query_embedding: the embedding of the query terms
// embeddings: the list of embeddings to select from
// lambda: MMR is a weighted selection of two opposing factors:
//    - relevance to the query
//    - "novelty" or, the measure of how minimal the similarity is
//      to existing documents in the selection
//      The value of lambda skews the weightage in favor of either relevance or novelty.
//    - we add a language diversity factor to the score to encourage a range of langauges in the results
//    - we also add a path diversity factor to the score to encourage a range of paths in the results
//  k: the number of embeddings to select
pub fn deduplicate_with_mmr(
    query_embedding: &[f32],
    embeddings: &[&[f32]],
    languages: &[&str],
    paths: &[&str],
    lambda: f32,
    k: usize,
) -> Vec<usize> {
    let mut idxs = vec![];
    let mut lang_counts = HashMap::new();
    let mut path_counts = HashMap::new();

    if embeddings.len() < k {
        return (0..embeddings.len()).collect();
    }

    while idxs.len() < k {
        let mut best_score = f32::NEG_INFINITY;
        let mut idx_to_add = None;

        for (i, emb) in embeddings.iter().enumerate() {
            if idxs.contains(&i) {
                continue;
            }
            let first_part = cosine_similarity(query_embedding, emb);
            let mut second_part = 0.;
            for j in idxs.iter() {
                let cos_sim = cosine_similarity(emb, embeddings[*j]);
                if cos_sim > second_part {
                    second_part = cos_sim;
                }
            }
            let mut equation_score = lambda * first_part - (1. - lambda) * second_part;

            // MMR + (1/2)^n where n is the number of times a language has been selected
            let lang_count = lang_counts.get(languages[i]).unwrap_or(&0);
            equation_score += 0.5_f32.powi(*lang_count);

            // MMR + (3/4)^n where n is the number of times a path has been selected
            let path_count = path_counts.get(paths[i]).unwrap_or(&0);
            equation_score += 0.75_f32.powi(*path_count);

            if equation_score > best_score {
                best_score = equation_score;
                idx_to_add = Some(i);
            }
        }
        if let Some(i) = idx_to_add {
            idxs.push(i);
            *lang_counts.entry(languages[i]).or_insert(0) += 1;
            *path_counts.entry(paths[i]).or_insert(0) += 1;
        }
    }
    idxs
}

fn dot(a: &[f32], b: &[f32]) -> f32 {
    a.iter().zip(b.iter()).map(|(ai, bi)| ai * bi).sum()
}

fn norm(a: &[f32]) -> f32 {
    dot(a, a)
}

fn cosine_similarity(a: &[f32], b: &[f32]) -> f32 {
    dot(a, b) / (norm(a) * norm(b))
}
