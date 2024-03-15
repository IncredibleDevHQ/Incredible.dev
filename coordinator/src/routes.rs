use crate::{controller::suggest, models::SuggestRequest};
use serde::Deserialize;
use warp::{self, http::Response, Filter};

extern crate common;
use common::CodeContext;

pub fn coordinator() -> impl Filter<Extract = impl warp::Reply, Error = warp::Rejection> + Clone {
    home_route().or(perform_suggest())
}

#[derive(Deserialize)]
pub struct RetrieveCodeRequest {
    pub code_context: Vec<CodeContext>,
}

/// POST /suggest
fn perform_suggest(
) -> impl Filter<Extract = impl warp::Reply, Error = warp::Rejection> + Clone {
    warp::path("suggest")
        .and(warp::post())
        .and(
            warp::body::content_length_limit(1024 * 16)
                .and(warp::body::json::<SuggestRequest>()),
        )
        .and_then(suggest::handle_modify_code_wrapper)
}

fn home_route() -> impl Filter<Extract = impl warp::Reply, Error = warp::Rejection> + Clone {
    warp::path::end() // Matches the root path "/"
        .and(warp::get()) // Only responds to GET requests
        .map(|| {
            Response::builder()
                .status(warp::http::StatusCode::OK)
                .body("Hello from coordinator")
                .expect("Failed to construct response")
        })
}
