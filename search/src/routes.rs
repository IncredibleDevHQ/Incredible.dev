use std::convert::Infallible;
use std::sync::Arc;
use warp::{self, Filter};

use crate::controller::symbol;
use crate::db::DbConnect;
use crate::graph::symbol_ops;
use crate::models::SymbolSearchRequest;

pub fn search_routes() -> impl Filter<Extract = impl warp::Reply, Error = warp::Rejection> + Clone {
    symbol_search()
}

/// POST /symbols
fn symbol_search() -> impl Filter<Extract = impl warp::Reply, Error = warp::Rejection> + Clone {
    warp::path("symbols")
        .and(warp::post())
        .and(json_body())
        .and_then(symbol::symbol_search)
}

/// Provides DbConnect instance wrapped in Arc<Mutex> to the next filter.
fn with_db(
    db: Arc<DbConnect>,
) -> impl Filter<Extract = (Arc<DbConnect>,), Error = Infallible> + Clone {
    warp::any().map(move || db.clone())
}

fn json_body() -> impl Filter<Extract = (SymbolSearchRequest,), Error = warp::Rejection> + Clone {
    warp::body::content_length_limit(1024 * 16).and(warp::body::json())
}
