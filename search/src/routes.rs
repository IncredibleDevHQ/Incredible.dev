extern crate common;
use common::CodeSpanRequest;

use std::convert::Infallible;
use std::sync::Arc;
use warp::{self, Filter};

use crate::controller::{parentscope, span, symbol};
use crate::db::DbConnect;
use crate::graph::symbol_ops;
use crate::models::{ParentScopeRequest, SymbolSearchRequest};
use crate::AppState;

use serde::Deserialize;

pub fn search_routes(
    app_state: Arc<AppState>,
) -> impl Filter<Extract = impl warp::Reply, Error = warp::Rejection> + Clone {
    symbol_search(app_state.clone())
        .or(span_code_chunk_retrieve(app_state.clone()))
        .or(parent_scope_retrieve(app_state.clone()))
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

/// GET /parentscope
/// Retrieves the code defining the parent scope based on the provided file path, line range, and optional id.
///
/// This endpoint listens for GET requests at the "/parentscope" path and expects query parameters
/// encapsulated in the `ParentScopeRequest` struct.
///
/// # Request Parameters
/// - `repo`: The name of the repository containing the file.
/// - `file`: The file path within the repository.
/// - `start_line`: The starting line number of the code range.
/// - `end_line`: The ending line number of the code range.
/// - `id`: An optional identifier for the request.
///
/// # Responses
/// - Returns a `warp::Reply` on success, containing the parent scope code.
/// - Returns a `warp::Rejection` in case of errors or if the request parameters are invalid.
fn parent_scope_retrieve(
    app_state: Arc<AppState>,
) -> impl Filter<Extract = impl warp::Reply, Error = warp::Rejection> + Clone {
    warp::path("parentscope")
        .and(warp::get())
        .and(warp::query::<ParentScopeRequest>())
        .and(warp::any().map(move || app_state.clone()))
        .and_then(parentscope::parent_scope_search) // Assuming you have a corresponding handler in the controller
}

/// Provides DbConnect instance wrapped in Arc<Mutex> to the next filter.
fn with_db(
    db: Arc<DbConnect>,
) -> impl Filter<Extract = (Arc<DbConnect>,), Error = Infallible> + Clone {
    warp::any().map(move || db.clone())
}
