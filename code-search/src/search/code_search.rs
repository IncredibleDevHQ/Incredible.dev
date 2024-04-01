use common::ast::graph_code_pluck::{ContentDocument, ExtractedContent};
use common::ast::symbol::SymbolLocations;
use common::hasher::generate_quikwit_index_name;
use log::debug;
use std::sync::Arc;

extern crate common;

use crate::db::DbConnect;
use crate::parser::literal::Literal;
use crate::search::payload::{CodeExtractMeta, PathExtractMeta, SymbolPayload};
use crate::search::ranking::rank_symbol_payloads;
use crate::AppState;
use common::models::CodeChunk;

use anyhow::{anyhow, Error, Result};
use serde::{Deserialize, Serialize};

use super::quikwit::get_file_from_quickwit;

const CODE_SEARCH_LIMIT: u64 = 10;

pub async fn code_search(
    query: &String,
    repo_name: &String,
    db_client: &DbConnect,
    app_state: Arc<AppState>,
) -> Result<Vec<CodeChunk>> {
    // performing semantic search on the symbols.
    log::debug!("semantic search\n");
    let results_symbol: Vec<crate::search::payload::SymbolPayload> = semantic_search_symbol(
        query.into(),
        CODE_SEARCH_LIMIT,
        0,
        0.0,
        true,
        db_client,
        repo_name,
    )
    .await?;

    log::debug!("semantic search results: {:?}", results_symbol);
    // for top 3 symbols, perform semantic search using the symbol as a query and print the results with good formatting
    for symbol in results_symbol.iter().take(10) {
        log::debug!(
                "Symbol semantic search on chunk: Symbol: {}, Score: {:?}, Relative paths: {:?}, Types: {:?}, isglobals:{:?}, node_types:{:?}",
                symbol.symbol, symbol.score, symbol.relative_paths, symbol.symbol_types, symbol.is_globals, symbol.node_kinds,
            );
    }

    let ranked_symbols = rank_symbol_payloads(&results_symbol);

    // iterate and print the top paths with score
    for meta in ranked_symbols.iter().take(10) {
        log::debug!("Path: {}, Score: {}", meta.path, meta.score);
    }
    // call self.get_scope_graph on top 3 paths from ranked_symbpls
    let extracted_chunks = process_paths(
        ranked_symbols.iter().cloned().take(10).collect(),
        repo_name,
        app_state,
    )
    .await?;

    // Most likely needs to be changed based on API response requirements
    // create codeChunks from the extracted_chunks and append to chunks
    let mut code_chunks = extracted_chunks
        .into_iter()
        .map(|chunk| {
            let relative_path = chunk.path;

            CodeChunk {
                path: relative_path.clone(),
                snippet: chunk.content,
                start_line: chunk.start_line as usize,
                end_line: chunk.end_line as usize,
            }
        })
        .collect::<Vec<_>>();

    // iterate and print the code chunks
    for code_chunk in code_chunks.iter().take(10) {
        log::debug!(
            "Code chunk: Path: {}, Start line: {}, End line: {}, Snippet: {}",
            code_chunk.path,
            code_chunk.start_line,
            code_chunk.end_line,
            code_chunk.snippet
        );
    }
    //chunks.append(&mut codeChunks);

    code_chunks.sort_by(|a, b| a.path.cmp(&b.path).then(a.start_line.cmp(&b.start_line)));

    Ok(code_chunks)
}

async fn semantic_search_symbol<'a>(
    query: Literal<'a>,
    limit: u64,
    offset: u64,
    threshold: f32,
    retrieve_more: bool,
    db_client: &DbConnect,
    repo_name: &String,
) -> Result<Vec<SymbolPayload>> {
    debug!("Repo name inside semantic search symbol: {:?}", repo_name);
    let semantic_result = db_client
        .semantic
        .search_symbol(query, limit, offset, threshold, retrieve_more, repo_name)
        .await;

    match semantic_result {
        Ok(result) => Ok(result),
        Err(err) => {
            log::error!("semantic search error: {:?}", err);
            Err(err)
        }
    }
}

async fn process_paths(
    path_extract_meta: Vec<PathExtractMeta>,
    repo_name: &String,
    app_state: Arc<AppState>,
) -> Result<Vec<ExtractedContent>, anyhow::Error> {
    // Initialize an empty vector to store the extracted contents.
    let mut results = Vec::new();

    // Iterate over each provided path and its associated metadata.
    for path_meta in &path_extract_meta {
        let path = &path_meta.path;

        log::debug!("inside process path: {:?}", path);
        // Fetch the content of the file for the current path.
        let app_state_clone = Arc::clone(&app_state);

        let source_document = get_file_content(path, repo_name, app_state_clone).await?;

        // log the error and continue to the next path if the file content is not found.
        if source_document.is_none() {
            log::debug!("file content not found for path: {:?}", path);
            continue;
        }

        // unwrap the source document
        let source_document = source_document.unwrap();

        // Deserialize the symbol locations embedded in the source document.
        let symbol_locations: SymbolLocations = source_document.symbol_locations()?;

        // Convert the compacted u8 array of line end indices back to their original u32 format.
        let line_end_indices: Vec<usize> = source_document.fetch_line_indices();
        // Retrieve the scope graph associated with symbol locations.
        let sg = symbol_locations
            .scope_graph()
            .ok_or_else(|| anyhow!("path not supported for /token-value"))?;

        // For each metadata about code extraction, process and extract the required content.
        let top_three_chunks: Vec<&CodeExtractMeta> =
            path_meta.code_extract_meta.iter().take(3).collect();

        for code_meta in top_three_chunks {
            let start_byte: usize = code_meta.start_byte.try_into().unwrap();
            let end_byte: usize = code_meta.end_byte.try_into().unwrap();

            // print the start and end byte
            log::debug!(
                "-symbol start_byte: {:?}, end_byte: {:?}, path: {}, score: {}",
                start_byte,
                end_byte,
                path,
                path_meta.score
            );

            let extraction_config = common::ast::graph_code_pluck::ExtractionConfig {
                code_byte_expansion_range: 300,
                min_lines_to_return: 8,
                max_lines_limit: Some(20),
            };

            let extract_content = sg.expand_scope(
                path,
                start_byte,
                end_byte,
                &source_document,
                &line_end_indices,
                &extraction_config,
            );

            // Store the extracted content in the results vector.
            results.push(extract_content);
        }
    }

    Ok(results)
}

pub async fn get_file_content(
    path: &str,
    repo_name: &String,
    app_state: Arc<AppState>,
) -> Result<Option<ContentDocument>> {
    let config = app_state.configuration.clone();
    let new_index_id = generate_quikwit_index_name(repo_name);

    log::debug!("fetching file content {}\n", path);
    get_file_from_quickwit(&new_index_id, "relative_path", path, app_state).await
}
