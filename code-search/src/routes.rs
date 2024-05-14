extern crate common;
use common::models::CodeSpanRequest;
use common::TokenInfoRequest;

use std::convert::Infallible;
use std::sync::Arc;
use warp::{self, http::Response, Filter};

use crate::controller::{navigator, parentscope, span, symbol};
use crate::db::DbConnect;
// use crate::graph::symbol_ops;
use crate::config::AppState;
use crate::models::{ParentScopeRequest, SymbolSearchRequest};

pub fn search_routes(
    app_state: Arc<AppState>,
) -> impl Filter<Extract = impl warp::Reply, Error = warp::Rejection> + Clone {
    symbol_search(app_state.clone())
        .or(health_check())
        .or(span_code_chunk_retrieve(app_state.clone()))
        .or(parent_scope_retrieve(app_state.clone()))
        .or(token_info_fetcher(app_state.clone()))
}

fn health_check() -> impl Filter<Extract = impl warp::Reply, Error = warp::Rejection> + Clone {
    warp::path::end() // Matches the root path "/"
        .and(warp::get()) // Only responds to GET requests
        .map(|| {
            Response::builder()
                .status(warp::http::StatusCode::OK)
                .body("Hello from code search")
                .expect("Failed to construct response")
        })
}

/// POST /symbols
fn symbol_search(
    app_state: Arc<AppState>,
) -> impl Filter<Extract = impl warp::Reply, Error = warp::Rejection> + Clone {
    warp::path("symbols")
        .and(warp::post())
        .and(
            warp::body::content_length_limit(1024 * 16)
                .and(warp::body::json::<SymbolSearchRequest>()),
        )
        .and(warp::any().map(move || app_state.clone()))
        .and_then(symbol::symbol_search)
}

/// Handles the POST request for retrieving code chunks for given spans (code range, e.g., line 15..35) within a repository's specific file and, optionally, a specific branch.
///
/// This endpoint listens for POST requests at the "/span" path and expects parameters
/// encapsulated in the `CodeSpanRequest` struct within the request body.
///
/// # Request Body
/// The request body should be a JSON object that includes the following fields:
/// - `repo`: The name of the repository to search within. This field is required.
/// - `branch`: An optional branch name in the repository. If not provided, the search may consider the default branch or all branches based on the implementation.
/// - `path`: The file path within the specified repository and branch. This field is required.
/// - `ranges`: An optional field specifying the range(s) within the file to search. If omitted, the entire file is considered. The range should be specified in a format understood by the server, such as a start and end line number.
/// - `id`: An optional unique identifier for the request, which can be used for request tracking or caching. If omitted, the request is processed without specific tracking or caching.
///
/// # Responses
/// - Returns a `warp::Reply` on success, encapsulating the search results in JSON format.
/// - Returns a `warp::Rejection` in case of errors or if the search criteria are not met.
///
/// # Example Request
/// A curl command to trigger this endpoint might look like this (note the use of `-X POST` and the JSON payload in the request body):
/// ```sh
/// curl -X POST "http://example.com/span" \
///      -H "Content-Type: application/json" \
///      -d '{"repo":"example-repo", "branch":"main", "path":"src/example.js", "ranges":[{"start":1, "end":5}], "id":"12345"}'
/// ```
fn span_code_chunk_retrieve(
    app_state: Arc<AppState>,
) -> impl Filter<Extract = impl warp::Reply, Error = warp::Rejection> + Clone {
    warp::path("span")
        .and(warp::post())
        .and(warp::body::content_length_limit(1024 * 16).and(warp::body::json::<CodeSpanRequest>()))
        .and(warp::any().map(move || app_state.clone()))
        .and_then(span::span_search)
}

// POST /parentscope
/// Retrieves hierarchical scope information for a specified segment of code within a file.
///
/// This endpoint listens for POST requests at the "/parentscope" path and expects a JSON payload
/// encapsulated in the `ParentScopeRequest` struct. The endpoint provides detailed hierarchical
/// scope information and code containing the expanded scope, facilitating a deeper understanding of the code's structure.
///
/// # Request Parameters
/// - `repo`: The name of the repository containing the file.
/// - `file`: The file path within the repository.
/// - `start_line`: The starting line number of the code range.
/// - `end_line`: The ending line number of the code range.
/// - `id`: An optional identifier for the request, used for tracking or caching purposes.
///
/// # Sample Request
/// ```json
/// {
///   "repo": "bloop-ai",
///   "file": "server/bleep/src/webserver/answer.rs",
///   "start_line": 191,
///   "end_line": 193
/// }
/// ```
///
/// # Responses
/// On success, the endpoint returns a JSON object containing the path, content, byte range, line range,
/// and the hierarchical scope map. In case of errors or invalid request parameters, a `warp::Rejection` is returned.
///
/// ## Successful Response Fields
/// - `path`: The path to the file for which the scope information was requested.
/// - `content`: The extracted content based on the provided line range, with additional context.
/// - `start_byte`: The starting byte index of the extracted content.
/// - `end_byte`: The ending byte index of the extracted content.
/// - `start_line`: The starting line number of the extracted content (may differ from the request).
/// - `end_line`: The ending line number of the extracted content (may differ from the request).
/// - `scope_map`: A string representation of the hierarchical scope structure related to the specified code.
///
/// ## Sample Response
/// ```json
/// {
///   "path": "server/bleep/src/webserver/answer.rs",
///   "content": "        if let Err(err) = response.as_ref() { ... }",
///   "start_byte": 4814,
///   "end_byte": 5354,
///   "start_line": 182,
///   "end_line": 195,
///   "scope_map": "<Root Scope Line number 1> use std::{...};\n    <Line number 178> impl AgentExecutor { ... }"
/// }
/// ```
///
fn parent_scope_retrieve(
    app_state: Arc<AppState>,
) -> impl Filter<Extract = impl warp::Reply, Error = warp::Rejection> + Clone {
    warp::path("parentscope")
        .and(warp::post())
        .and(
            warp::body::content_length_limit(1024 * 16)
                .and(warp::body::json::<ParentScopeRequest>()),
        )
        .and(warp::any().map(move || app_state.clone()))
        .and_then(parentscope::parent_scope_search) // Assuming you have a corresponding handler in the controller
}

fn token_info_fetcher(
    app_state: Arc<AppState>,
) -> impl Filter<Extract = impl warp::Reply, Error = warp::Rejection> + Clone {
    warp::path("token_info")
        .and(warp::post())
        .and(
            warp::body::content_length_limit(1024 * 16).and(warp::body::json::<TokenInfoRequest>()),
        )
        .and(warp::any().map(move || app_state.clone()))
        .and_then(navigator::handle_token_info_fetcher_wrapper) // Assuming you have a corresponding handler in the controller
}

/// Provides DbConnect instance wrapped in Arc<Mutex> to the next filter.
fn with_db(
    db: Arc<DbConnect>,
) -> impl Filter<Extract = (Arc<DbConnect>,), Error = Infallible> + Clone {
    warp::any().map(move || db.clone())
}
