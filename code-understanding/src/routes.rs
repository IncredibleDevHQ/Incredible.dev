use crate::controller;
use crate::AppState;
use std::sync::Arc;
use common::models::CodeUnderstandRequest;
use warp::{self, http::Response, Filter};

pub fn code_retrieve(
    app_state: Arc<AppState>,
) -> impl Filter<Extract = impl warp::Reply, Error = warp::Rejection> + Clone {
    home_route()
        .or(retrieve_code(app_state.clone()))
        .or(question_list())
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

/// POST /question-list
/// # Request Body
/// The request body should contain a JSON object with two fields:
/// - `issue_desc`: A string representing the issue description.
/// - `repo_name`: A string representing the repository name.
///
/// Example JSON body:
/// ```json
/// {
///     "issue_desc": "I'm encountering an issue with the login functionality.",
///     "repo_name": "example-repo"
/// }
/// ```
///
/// # Responses
/// - Returns a `warp::Reply` on success, indicating that the questions have been successfully received.
/// - Returns a `warp::Rejection` in case of errors during request processing.

fn question_list() -> impl Filter<Extract = impl warp::Reply, Error = warp::Rejection> + Clone {
    warp::path("question-list")
        .and(warp::post())
        .and(warp::body::json())
        .and_then(controller::generate_question_array)
}
