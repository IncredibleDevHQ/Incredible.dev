use crate::{controller::modifier, models::CodeModifierRequest};
use serde::Deserialize;
use warp::{self, http::Response, Filter};

extern crate common;
use common::CodeContext;

pub fn modify_code() -> impl Filter<Extract = impl warp::Reply, Error = warp::Rejection> + Clone {
    home_route().or(perform_code_modifications())
}

#[derive(Deserialize)]
pub struct RetrieveCodeRequest {
    pub code_context: Vec<CodeContext>,
}

/// POST /modify_code
fn perform_code_modifications(
) -> impl Filter<Extract = impl warp::Reply, Error = warp::Rejection> + Clone {
    warp::path("modify_code")
        .and(warp::post())
        .and(
            warp::body::content_length_limit(1024 * 16)
                .and(warp::body::json::<CodeModifierRequest>()),
        )
        .and_then(modifier::handle_modify_code_wrapper)
}

fn home_route() -> impl Filter<Extract = impl warp::Reply, Error = warp::Rejection> + Clone {
    warp::path::end() // Matches the root path "/"
        .and(warp::get()) // Only responds to GET requests
        .map(|| {
            Response::builder()
                .status(warp::http::StatusCode::OK)
                .body("Hello from code retrieve")
                .expect("Failed to construct response")
        })
}
