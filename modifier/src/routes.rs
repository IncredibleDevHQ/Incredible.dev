use crate::controller;
use serde::Deserialize;
use std::sync::Arc;
use warp::{self, http::Response, Filter};
use crate::AppState;

extern crate common;
use common::CodeContext;

pub fn modify_code(app_state: Arc<AppState>) -> impl Filter<Extract = impl warp::Reply, Error = warp::Rejection> + Clone {
    home_route().or(perform_code_modifications(app_state.clone()))
}

#[derive(Deserialize)]
pub struct RetrieveCodeRequest {
    pub code_context: Vec<CodeContext>,
}

/// GET /modify-code?query=<query>&repo=<repo_name>
fn perform_code_modifications(app_state: Arc<AppState>) -> impl Filter<Extract = impl warp::Reply, Error = warp::Rejection> + Clone {
    warp::path("modify-code")
        .and(warp::get())
        .and(warp::query::<RetrieveCodeRequest>())
        .and(warp::any().map(move || app_state.clone()))
        .and_then(controller::handle_modify_code)
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
