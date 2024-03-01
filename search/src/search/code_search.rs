use std::sync::Arc;

use crate::db::DbConnect;
use crate::graph::scope_graph::SymbolLocations;
use crate::graph::symbol_ops;
use crate::models::CodeChunk;
use crate::parser::literal::Literal;
use crate::search::payload::{CodeExtractMeta, PathExtractMeta, SymbolPayload};
use crate::search::ranking::rank_symbol_payloads;
use crate::utilities::util::get_line_number;

use anyhow::{anyhow, Error, Result};
use serde::{Deserialize, Serialize};

use super::quikwit::get_file_from_quickwit;
use md5::compute;

#[derive(Serialize, Deserialize, Default, Debug, Clone)]
pub struct ExtractedContent {
    pub path: String,
    pub content: String,
    pub start_byte: usize,
    pub end_byte: usize,
    pub start_line: usize,
    pub end_line: usize,
}

#[derive(Default, Debug, Clone, Serialize)]
pub struct ExtractionConfig {
    pub code_byte_expansion_range: usize,  // Number of bytes to expand from the start and end.
    pub min_lines_to_return: usize,        // Minimum number of lines the extraction should return.
    pub max_lines_limit: Option<usize>,    // Optional maximum number of lines to extract.
}


#[derive(Default, Debug, Clone, Serialize)]
pub struct ContentDocument {
    pub repo_name: String,
    pub repo_ref: String,
    pub relative_path: String,
    pub lang: Option<String>,
    pub line_end_indices: Vec<u8>,
    pub content: String,
    pub symbol_locations: Vec<u8>,
    pub symbols: String,
}

impl ContentDocument {
    pub fn fetch_line_indices(&self) -> Vec<usize> {
        let line_end_indices: Vec<usize> = self
        .line_end_indices
        .chunks(4)
        .filter_map(|chunk| {
            // Convert each 4-byte chunk to a u32.
            if chunk.len() == 4 {
                let value =
                    u32::from_le_bytes([chunk[0], chunk[1], chunk[2], chunk[3]]) as usize;
                Some(value)
            } else {
                None
            }
        })
        .collect();

       line_end_indices
    }
    pub fn symbol_locations(&self) -> Result<SymbolLocations> {
        let symbol_locations = bincode::deserialize::<SymbolLocations>(&self.symbol_locations)?;
        Ok(symbol_locations)
    }
}

const CODE_SEARCH_LIMIT: u64 = 10;

pub async fn code_search(
    query: &String,
    repo_name: &String,
    db_client: &DbConnect,
) -> Result<Vec<CodeChunk>> {
    // performing semantic search on the symbols.
    println!("semantic search\n");
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

    println!("semantic search results: {:?}", results_symbol);
    // for top 3 symbols, perform semantic search using the symbol as a query and print the results with good formatting
    for symbol in results_symbol.iter().take(10) {
        println!(
                "Symbol semantic search on chunk: Symbol: {}, Score: {:?}, Relative paths: {:?}, Types: {:?}, isglobals:{:?}, node_types:{:?}",
                symbol.symbol, symbol.score, symbol.relative_paths, symbol.symbol_types, symbol.is_globals, symbol.node_kinds,
            );
    }

    let ranked_symbols = rank_symbol_payloads(&results_symbol);

    // iterate and print the top paths with score
    for meta in ranked_symbols.iter().take(10) {
        println!("Path: {}, Score: {}", meta.path, meta.score);
    }
    // call self.get_scope_graph on top 3 paths from ranked_symbpls
    let extracted_chunks =
        process_paths(ranked_symbols.iter().cloned().take(10).collect(), repo_name).await?;

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
        println!(
            "Code chunk: Path: {}, Start line: {}, End line: {}, Snippet: {}",
            code_chunk.path, code_chunk.start_line, code_chunk.end_line, code_chunk.snippet
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
    let semantic_result = db_client
        .semantic
        .search_symbol(query, limit, offset, threshold, retrieve_more, repo_name)
        .await;

    match semantic_result {
        Ok(result) => Ok(result),
        Err(err) => {
            println!("semantic search error: {:?}", err);
            Err(err)
        }
    }
}

async fn process_paths(
    path_extract_meta: Vec<PathExtractMeta>,
    repo_name: &String,
) -> Result<Vec<ExtractedContent>, anyhow::Error> {
    // Initialize an empty vector to store the extracted contents.
    let mut results = Vec::new();

    // Iterate over each provided path and its associated metadata.
    for path_meta in &path_extract_meta {
        let path = &path_meta.path;

        println!("inside process path: {:?}", path);
        // Fetch the content of the file for the current path.
        let source_document = get_file_content(path, repo_name).await?;

        // log the error and continue to the next path if the file content is not found.
        if source_document.is_none() {
            println!("file content not found for path: {:?}", path);
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
            println!(
                "-symbol start_byte: {:?}, end_byte: {:?}, path: {}, score: {}",
                start_byte, end_byte, path, path_meta.score
            );

            let extraction_config = ExtractionConfig {
                code_byte_expansion_range: 300,
                min_lines_to_return: 8,
                max_lines_limit: Some(20),
            };
            
            let extract_content = sg.expand_scope(path, start_byte, end_byte, &source_document, 
                 &line_end_indices, &extraction_config);

            // Store the extracted content in the results vector.
            results.push(extract_content);
        }
    }

    Ok(results)
}

// Input is repo name in format v2/owner_name/repo_name.
// We generate hash of namespace using md5 and prefix it with the repo name extracted from namespace.
pub fn generate_quikwit_index_name(namespace: &str) -> String {
    let repo_name = namespace.split("/").last().unwrap();
    let version = namespace.split("/").nth(0).unwrap();
    let md5_index_id = compute(namespace);
    // create a hex string
    let new_index_id = format!("{:x}", md5_index_id);
    let index_name = format!("{}-{}-{}", version, repo_name, new_index_id);
    return index_name;
}

pub async fn get_file_content(path: &str, repo_name: &String) -> Result<Option<ContentDocument>> {
    let new_index_id = generate_quikwit_index_name(repo_name);
    // println!("fetching file content {}\n", path);
    get_file_from_quickwit(&new_index_id, "relative_path", path).await
}
