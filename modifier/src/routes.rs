use crate::AppState;
use crate::{controller::modifier, models::CodeModifierRequest};
use serde::Deserialize;
use std::sync::Arc;
use warp::{self, http::Response, Filter};

extern crate common;
use common::CodeContext;

pub fn modify_code(
    app_state: Arc<AppState>,
) -> impl Filter<Extract = impl warp::Reply, Error = warp::Rejection> + Clone {
    home_route().or(perform_code_modifications(app_state.clone()))
}

#[derive(Deserialize)]
pub struct RetrieveCodeRequest {
    pub code_context: Vec<CodeContext>,
}

/// POST /modify_code
fn perform_code_modifications(
    app_state: Arc<AppState>,
) -> impl Filter<Extract = impl warp::Reply, Error = warp::Rejection> + Clone {
    warp::path("modify_code")
        .and(warp::post())
        .and(
            warp::body::content_length_limit(1024 * 16)
                .and(warp::body::json::<CodeModifierRequest>()),
        )
        .and(warp::any().map(move || app_state.clone()))
        .and_then(modifier::handle_modify_code)
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
