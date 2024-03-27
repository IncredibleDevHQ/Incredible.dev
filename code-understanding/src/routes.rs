use crate::controller;
use crate::AppState;
use common::models::CodeUnderstandRequest;
use std::sync::Arc;
use warp::{self, http::Response, Filter};

pub fn code_retrieve(
    app_state: Arc<AppState>,
) -> impl Filter<Extract = impl warp::Reply, Error = warp::Rejection> + Clone {
    home_route()
        .or(retrieve_code(app_state.clone()))
}

/// GET /retrieve-code?query=<query>&repo=<repo_name>
fn retrieve_code(
    app_state: Arc<AppState>,
) -> impl Filter<Extract = impl warp::Reply, Error = warp::Rejection> + Clone {
    warp::path("retrieve-code")
        .and(warp::get())
        .and(warp::query::<CodeUnderstandRequest>())
        .and(warp::any().map(move || app_state.clone()))
        .and_then(controller::handle_retrieve_code)
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
