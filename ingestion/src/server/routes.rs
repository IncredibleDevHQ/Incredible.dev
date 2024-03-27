use warp::{self, http::Response, Filter};

use super::{controller, models::CodeIndexingRequest};

pub fn ingestion() -> impl Filter<Extract = impl warp::Reply, Error = warp::Rejection> + Clone {
    home_route().or(start_indexing())
}

/// POST /index
fn start_indexing() -> impl Filter<Extract = impl warp::Reply, Error = warp::Rejection> + Clone {
    warp::path("index")
        .and(warp::post())
        .and(
            warp::body::content_length_limit(1024 * 16)
                .and(warp::body::json::<CodeIndexingRequest>()),
        )
        .and_then(controller::handle_code_index_wrapper)
}

fn home_route() -> impl Filter<Extract = impl warp::Reply, Error = warp::Rejection> + Clone {
    warp::path::end() // Matches the root path "/"
        .and(warp::get()) // Only responds to GET requests
        .map(|| {
            Response::builder()
                .status(warp::http::StatusCode::OK)
                .body("Hello from ingestion!")
                .expect("Failed to construct response")
        })
}
