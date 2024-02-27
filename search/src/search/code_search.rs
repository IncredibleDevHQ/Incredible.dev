use std::sync::Arc;

use crate::db::DbConnect;
use crate::graph::scope_graph::{get_line_number, SymbolLocations};
use crate::graph::symbol_ops;
use crate::models::CodeChunk;
use crate::parser::literal::Literal;
use crate::search::payload::{CodeExtractMeta, PathExtractMeta, SymbolPayload};
use crate::search::ranking::rank_symbol_payloads;
use anyhow::{anyhow, Error, Result};
use serde::Serialize;

use super::quikwit::get_file_from_quickwit;
use md5::compute;

#[derive(Default, Debug, Clone)]
pub struct ExtractedContent {
    pub path: String,
    pub content: String,
    pub start_byte: usize,
    pub end_byte: usize,
    pub start_line: usize,
    pub end_line: usize,
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

const CODE_SEARCH_LIMIT: u64 = 10;

pub async fn code_search(
    query: &String,
    repo_name: &String,
    db_client: Result<DbConnect, Error>,
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
    db_client: Result<DbConnect, Error>,
    repo_name: &String,
) -> Result<Vec<SymbolPayload>> {
    let semantic_result = db_client
        .unwrap()
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
        let symbol_locations: SymbolLocations =
            bincode::deserialize::<SymbolLocations>(&source_document.symbol_locations).unwrap();

        // Convert the compacted u8 array of line end indices back to their original u32 format.
        let line_end_indices: Vec<usize> = source_document
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

            let mut new_start = start_byte.clone();
            let mut new_end = end_byte.clone();
            // print the start and end byte
            println!(
                "-symbol start_byte: {:?}, end_byte: {:?}, path: {}, score: {}",
                start_byte, end_byte, path, path_meta.score
            );
            // Locate the node in the scope graph that spans the range defined by start and end bytes.
            let node_idx = sg.node_by_range(start_byte, end_byte);

            // If we can't find such a node, skip to the next metadata.
            if node_idx.is_none() {
                // find start and end bytes for 100 bytes above start and 200 bytes below end
                // check if the start byte greater than 100
                // check if the end byte less than the length of the file
                // if yes, then set the new start and end bytes
                // print the new start and end bytes
                println!("start_byte: {:?}, end_byte: {:?}", start_byte, end_byte);
                if start_byte > 300 {
                    new_start = start_byte - 300;
                } else {
                    new_start = 0;
                }

                if end_byte + 300 < source_document.content.len() {
                    new_end = end_byte + 300;
                } else {
                    new_end = source_document.content.len();
                }
                (new_start, new_end) = adjust_byte_positions(new_start, new_end, &line_end_indices);

                // print the new start and end
                println!("---new_start: {:?}, new_end: {:?}", new_start, new_end);
                let content = source_document.content[new_start..new_end].to_string();
                // print content
                println!(
                    "--- nodexxx content: symbol: {} \n{:?}\n",
                    code_meta.symbol, content
                );
            } else {
                let node_idx = node_idx.unwrap();

                // Get the byte range of the found node.
                let range: symbol_ops::TextRange =
                    sg.graph[sg.value_of_definition(node_idx).unwrap_or(node_idx)].range();

                // Adjust the starting byte to the beginning of the line.
                new_start = range.start.byte - range.start.column;

                // Determine the end byte based on the line end index or the range's end.
                new_end = line_end_indices
                    .get(range.end.line)
                    .map(|l| *l as usize)
                    .unwrap_or(range.end.byte);

                println!(
                    "Inside else adjusted start and end bytes: {:?}, {:?}",
                    new_start, new_end
                );
                // Convert byte positions back to line numbers to identify the extracted range's start and end lines.
                let starting_line = get_line_number(new_start, &line_end_indices);
                let ending_line = get_line_number(new_end, &line_end_indices);
                println!(
                    "Inside else adjusted start and end lines: {:?}, {:?}",
                    starting_line, ending_line
                );
                // subtract starting and ending line
                let total_lines = ending_line - starting_line;

                if total_lines < 8 {
                    println!("---new_start: {:?}, new_end: {:?}", new_start, new_end);
                    // Adjustments for ensuring content context.

                    // Ensure the extracted content doesn't exceed the document's bounds.
                    let mut temp_new_end = new_end.clone();
                    if new_end + 300 > source_document.content.len() {
                        new_end = source_document.content.len();
                        temp_new_end = source_document.content.len() - 2;
                    } else {
                        new_end += 300;
                        temp_new_end += 300;
                    }
                    (new_start, new_end) =
                        adjust_byte_positions(new_start, temp_new_end, &line_end_indices);
                } else if total_lines > 20 {
                    // If the extracted content exceeds 25 lines, change the end byte to the end of the 25th line.
                    new_end = line_end_indices
                        .get(starting_line + 20)
                        .map(|l| *l as usize)
                        .unwrap_or(new_end);
                }
                // print new start and end
            }

            // find starting line and ending line
            let ending_line = get_line_number(new_end, &line_end_indices);
            let starting_line = get_line_number(new_start, &line_end_indices);

            // Extract the desired content slice from the source document.
            let content = source_document.content[new_start..new_end].to_string();

            // Construct the extracted content object.
            let extract_content = ExtractedContent {
                path: path.clone(),
                content,
                start_byte: new_start,
                end_byte: new_end,
                start_line: starting_line,
                end_line: ending_line,
            };

            // Store the extracted content in the results vector.
            results.push(extract_content);
        }
    }

    Ok(results)
}

pub fn adjust_byte_positions(
    new_start: usize,
    temp_new_end: usize,
    line_end_indices: &Vec<usize>,
) -> (usize, usize) {
    let ending_line = get_line_number(temp_new_end, &line_end_indices);
    let starting_line = get_line_number(new_start, &line_end_indices);

    // If possible, use the ending of the previous line to determine the start of the current line.
    let mut previous_line = starting_line;
    if previous_line > 0 {
        previous_line -= 1;
    }

    // Adjust the start and end byte positions based on line numbers for a clearer context.
    let adjusted_start = line_end_indices
        .get(previous_line)
        .map(|l| *l as usize)
        .unwrap_or(new_start)
        + 1;
    let adjusted_end = line_end_indices
        .get(ending_line)
        .map(|l: &usize| *l as usize)
        .unwrap_or(temp_new_end);

    (adjusted_start, adjusted_end)
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
