use crate::agent::agent::Agent;
use crate::parser::parser::Literal;
use crate::search::payload::{Payload, SymbolPayload};
use crate::search::semantic::{Semantic, SemanticQuery, make_kv_keyword_filter, deduplicate_snippets};
use anyhow::Result;
use tracing::debug;
use tracing::instrument;
use qdrant_client::qdrant::{ScoredPoint, SearchPoints, WithPayloadSelector, WithVectorsSelector, Filter, Condition, with_payload_selector, with_vectors_selector};


pub type Embedding = Vec<f32>;


impl Agent {
    pub async fn semantic_search<'a>(
        &'a self,
        query: Literal<'a>,
        limit: u64,
        offset: u64,
        threshold: f32,
        retrieve_more: bool,
    ) -> Result<Vec<Payload>> {
        let query = SemanticQuery {
            target: Some(query),
            ..self.last_exchange().query.clone()
        };

        debug!(?query, "executing semantic query");
        let semantic_result = self
            .db
            .semantic
            .search(&query, limit, offset, threshold, retrieve_more)
            .await;

        match semantic_result {
            Ok(result) => {
                // loop through the result and print the relative path, language, sniipet, start line and end line.
                // for chunk in result.clone() {
                //     println!("relative_path: {:?}", chunk.relative_path);
                //     println!("lang: {:?}", chunk.lang);
                //     println!("snippet: {:?}", chunk.text);
                //     println!("start_line: {:?}", chunk.start_line);
                //     println!("end_line: {:?}\n", chunk.end_line);
                // }

                //println!("semantic search result: {:?}", result.);
                Ok(result)
            }
            Err(err) => {
                println!("semantic search error: {:?}", err);
                Err(err)
            }
        }
    }

    pub async fn semantic_search_symbol<'a>(
        &'a self,
        query: Literal<'a>,
        limit: u64,
        offset: u64,
        threshold: f32,
        retrieve_more: bool,
    ) -> Result<Vec<SymbolPayload>> {
        let query = SemanticQuery {
            target: Some(query),
            ..self.last_exchange().query.clone()
        };

        debug!(?query, "executing semantic query");
        let semantic_result = self
            .db
            .semantic
            .search_symbol(&query, limit, offset, threshold, retrieve_more)
            .await;

        match semantic_result {
            Ok(result) => {
                // loop through the result and print the relative path, language, sniipet, start line and end line.
                // for chunk in result.clone() {
                //     println!("relative_path: {:?}", chunk.relative_path);
                //     println!("lang: {:?}", chunk.lang);
                //     println!("snippet: {:?}", chunk.text);
                //     println!("start_line: {:?}", chunk.start_line);
                //     println!("end_line: {:?}\n", chunk.end_line);
                // }

                //println!("semantic search result: {:?}", result.);
                Ok(result)
            }
            Err(err) => {
                println!("semantic search error: {:?}", err);
                Err(err)
            }
        }
    }
}

impl Semantic {
    pub async fn search_with<'a>(
        &self,
        collection_name: &str,
        parsed_query: &SemanticQuery<'a>,
        vector: Embedding,
        limit: u64,
        offset: u64,
        threshold: f32,
    ) -> anyhow::Result<Vec<ScoredPoint>> {
        let mut conditions: Vec<Condition> = Vec::new();

        conditions.push(make_kv_keyword_filter("repo_name", &self.repo_name).into());

        let response = self
            .qdrant
            .search_points(&SearchPoints {
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
            })
            .await?;

        // iterate through the results and print the score and payload from each entry in the results
        let mut results = response.result.clone();
        results.sort_by(|a, b| b.score.partial_cmp(&a.score).unwrap());

        println!("---------xxxxxxxxxxxxxxx----------------");
        //println!("{:?}",results.clone());

        let acc = results
            .iter()
            .flat_map(|result| {
                let payload = result.payload.clone();
                let score = result.score;

                Some((payload, score))
            })
            .map(|(payload, score)| {
                //println!("payload: {:?}", payload);
                //println!("score: {:?}", score);
            })
            .collect::<Vec<_>>();

        Ok(response.result)
    }

    // function to perform semantic search on the symbols.
    pub async fn search_symbol<'a>(
        &self,
        parsed_query: &SemanticQuery<'a>,
        limit: u64,
        offset: u64,
        threshold: f32,
        retrieve_more: bool,
    ) -> anyhow::Result<Vec<SymbolPayload>> {
        let Some(query) = parsed_query.target() else {
            anyhow::bail!("no search target for query");
        };
        let vector = self.embed(&query)?;

        // TODO: Remove the need for `retrieve_more`. It's here because:
        // In /q `limit` is the maximum number of results returned (the actual number will often be lower due to deduplication)
        // In /answer we want to retrieve `limit` results exactly
        let results = self
            .search_with(
                "documents_symbol",
                parsed_query,
                vector.clone(),
                if retrieve_more { limit * 2 } else { limit }, // Retrieve double `limit` and deduplicate
                offset,
                threshold,
            )
            .await
            .map(|raw| {
                raw.into_iter()
                    .map(SymbolPayload::from_qdrant)
                    .collect::<Vec<_>>()
            })?;
        Ok(results)
    }

    pub async fn search<'a>(
        &self,
        parsed_query: &SemanticQuery<'a>,
        limit: u64,
        offset: u64,
        threshold: f32,
        retrieve_more: bool,
    ) -> anyhow::Result<Vec<Payload>> {
        let Some(query) = parsed_query.target() else {
            anyhow::bail!("no search target for query");
        };
        let vector = self.embed(&query)?;

        // TODO: Remove the need for `retrieve_more`. It's here because:
        // In /q `limit` is the maximum number of results returned (the actual number will often be lower due to deduplication)
        // In /answer we want to retrieve `limit` results exactly
        let results = self
            .search_with(
                &self.qdrant_collection_name,
                parsed_query,
                vector.clone(),
                if retrieve_more { limit * 2 } else { limit }, // Retrieve double `limit` and deduplicate
                offset,
                threshold,
            )
            .await
            .map(|raw| {
                raw.into_iter()
                    .map(Payload::from_qdrant)
                    .collect::<Vec<_>>()
            })?;
        Ok(deduplicate_snippets(results, vector, limit))
    }
}
