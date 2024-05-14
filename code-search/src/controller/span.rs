use std::sync::Arc;
extern crate common;

use crate::{config::AppState, search::code_search::get_file_content};
use crate::utilities::util::pluck_code_by_lines;
use common::{models::CodeSpanRequest, CodeChunk};

/// Asynchronously handles a search request for a specific span within a file in a repository.
///
/// # Parameters
/// - `params`: An instance of `SpanSearchRequest` containing the necessary parameters to perform the search.
///
/// # Returns
/// - An `Ok` variant of `Result` containing an `impl warp::Reply` that represents the HTTP response,
///   which varies based on the outcome of the file content retrieval.
pub async fn span_search(
    params: CodeSpanRequest,
    app_state: Arc<AppState>,
) -> Result<impl warp::Reply, warp::Rejection> {
    // Clone necessary parameters from the request for local use.
    let path = params.path.clone();
    let repo_name = params.repo.clone();

    // Attempt to retrieve the file content asynchronously based on the provided path and repository name.
    let source_document = get_file_content(&path, &repo_name, app_state).await;

    match source_document {
        Ok(content) => {
            // Determine the response based on the content availability.
            if content.is_none() {
                // If no content is found, construct a NOT FOUND response.
                // TODO: Create a generic Error response structure instead of returning plain text.
                let response = format!("No content found for the file: {}", path);
                Ok(warp::reply::with_status(
                    warp::reply::json(&response),
                    warp::http::StatusCode::NOT_FOUND,
                ))
            } else {
                let content_doc = content.unwrap();
                let code_file = content_doc.content.clone();

                if let Some(ranges) = &params.ranges {
                    if !ranges.is_empty() {
                        // Convert the compacted u8 array of line end indices back to their original u32 format.
                        let line_end_indices = content_doc.fetch_line_indices();

                        let code_chunks: Vec<CodeChunk> = ranges
                            .iter()
                            .filter_map(|range| {
                                match pluck_code_by_lines(
                                    &code_file,
                                    &line_end_indices,
                                    Some(range.start),
                                    Some(range.end),
                                ) {
                                    Ok(code_chunk) => Some(CodeChunk {
                                        path: path.clone(),
                                        snippet: code_chunk.to_string(),
                                        start_line: range.start,
                                        end_line: range.end,
                                    }),
                                    Err(e) => {
                                        log::error!("Error processing range {:?}: {}", range, e);
                                        None // Skip this entry
                                    }
                                }
                            })
                            .collect();

                        return Ok(warp::reply::with_status(
                            warp::reply::json(&code_chunks),
                            warp::http::StatusCode::OK,
                        ));
                    }
                }

                // If ranges is None or empty, or if the code above does not execute, return the entire content
                Ok(warp::reply::with_status(
                    warp::reply::json(&Vec::from([CodeChunk {
                        path: path.clone(),
                        snippet: code_file.to_string(),
                        start_line: 1,
                        end_line: code_file.lines().count(),
                    }])),
                    warp::http::StatusCode::OK,
                ))
            }
        }
        Err(e) => {
            // If an error occurs during content retrieval, construct an INTERNAL SERVER ERROR response.
            // TODO: Create a generic Error response structure instead of returning plain text.
            let response = format!("Error: {}", e);
            Ok(warp::reply::with_status(
                warp::reply::json(&response),
                warp::http::StatusCode::INTERNAL_SERVER_ERROR,
            ))
        }
    }
}
