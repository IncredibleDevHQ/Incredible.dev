use std::convert::Infallible;
use std::sync::Arc;
use warp::{self, Filter};

use crate::controller::{symbol, span};
use crate::db::DbConnect;
use crate::graph::symbol_ops;
use crate::models::{SymbolSearchRequest, SpanSearchRequest};
use serde::Deserialize;

pub fn search_routes() -> impl Filter<Extract = impl warp::Reply, Error = warp::Rejection> + Clone {
    symbol_search().or(span_code_chunk_retrieve())
}

/// POST /symbols
fn symbol_search() -> impl Filter<Extract = impl warp::Reply, Error = warp::Rejection> + Clone {
    warp::path("symbols")
        .and(warp::post())
        .and(warp::body::content_length_limit(1024 * 16).and(warp::body::json::<SymbolSearchRequest>()))
        .and_then(symbol::symbol_search)
}

/// Handles the GET request for retrieving code chunks for given  spans (code range ex: line 15..35) within a repository's specific file and, optionally, a specific branch.
///
/// This endpoint listens for GET requests at the "/span" path and expects query parameters
/// encapsulated in the `SpanSearchRequest` struct. 
///
/// # Request Parameters
/// - `repo`: The name of the repository to search within. This parameter is required.
/// - `branch`: An optional branch name in the repository. If not provided, the search may consider the default branch or all branches based on the implementation.
/// - `path`: The file path within the specified repository and branch. This parameter is required.
/// - `range`: An optional string specifying the range within the file to search. If omitted, the entire file is considered.
/// - `id`: An optional unique identifier for the request, which can be used for request tracking or caching. If omitted, the request is processed without specific tracking or caching.
///
/// # Responses
/// - Returns a `warp::Reply` on success, encapsulating the search results.
/// - Returns a `warp::Rejection` in case of errors or if the search criteria are not met.
///

fn span_code_chunk_retrieve() -> impl Filter<Extract = impl warp::Reply, Error = warp::Rejection> + Clone {
    warp::path("span")
        .and(warp::get())
        .and(warp::query::<SpanSearchRequest>())
        .and_then(span::span_search)
}

/// Provides DbConnect instance wrapped in Arc<Mutex> to the next filter.
fn with_db(
    db: Arc<DbConnect>,
) -> impl Filter<Extract = (Arc<DbConnect>,), Error = Infallible> + Clone {
    warp::any().map(move || db.clone())
}
