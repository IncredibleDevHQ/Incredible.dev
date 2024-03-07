use crate::controller;
use serde::Deserialize;
use std::sync::Arc;
use warp::{self, http::Response, Filter};
use crate::AppState;

extern crate common;
use common::CodeUnderstandings;

// fetch_code_context sets up the routes for the API. It combines the home route and the
// route to expand and find code context based on the app state.

// Sample usage:

// curl -X POST http://your-api-endpoint.com/find-code-context \
//      -H "Content-Type: application/json" \
//      -d '{
//          "qna_context": {
//              "repo": "your-repo-url",
//              "issue_description": "Sample issue description for context",
//              "qna": [
//                  {
//                      "context": [
//                          {
//                              "path": "src/main.rs",
//                              "hidden": false,
//                              "repo": "your-repo-url",
//                              "branch": "main",
//                              "ranges": [{"start": 10, "end": 20}]
//                          },
//                          {
//                              "path": "src/lib.rs",
//                              "hidden": false,
//                              "repo": "your-repo-url",
//                              "branch": "main",
//                              "ranges": [{"start": 15, "end": 25}, {"start": 30, "end": 40}]
//                          }
//                      ],
//                      "question": "How does the function work?",
//                      "answer": "The function works by..."
//                  },
//                  {
//                      "context": [
//                          {
//                              "path": "src/utils.rs",
//                              "hidden": false,
//                              "repo": "your-repo-url",
//                              "branch": "dev",
//                              "ranges": [{"start": 50, "end": 60}]
//                          }
//                      ],
//                      "question": "What is the purpose of this utility function?",
//                      "answer": "This utility function is used for..."
//                  }
//              ]
//          }
//      }'

pub fn fetch_code_context(app_state: Arc<AppState>) -> impl Filter<Extract = impl warp::Reply, Error = warp::Rejection> + Clone {
    // Combines the home route with the expand_find_code_context route.
    // The expand_find_code_context route is provided with a cloned app_state
    // to ensure thread-safe state sharing across requests.
    home_route().or(expand_find_code_context(app_state.clone()))
}

// RetrieveCodeRequest struct defines the expected structure of the JSON payload
// for the POST /find-code-context endpoint.
#[derive(Deserialize)]
pub struct RetrieveCodeRequest {
    // Contains the detailed code understandings and issue description to be processed.
    pub qna_context: CodeUnderstandings,
}

// Find the API doc here https://www.notion.so/Context-generator-b7941ee220e54c979095c563bf746611?pvs=4
// expand_find_code_context sets up the Warp filter for the find-code-context endpoint.
// This function constructs a filter chain that captures the POST request to find code context.
fn expand_find_code_context(app_state: Arc<AppState>) -> impl Filter<Extract = impl warp::Reply, Error = warp::Rejection> + Clone {
    // Specifies the endpoint path.
    warp::path("find-code-context")
        // Specifies that this route accepts POST requests.
        .and(warp::post())
        // Extracts the JSON body as a RetrieveCodeRequest, ensuring the request structure matches the expected format.
        .and(warp::body::json::<RetrieveCodeRequest>())
        // Clones and passes the app_state to subsequent handlers, ensuring each handler has access to the shared state.
        .and(warp::any().map(move || app_state.clone()))
        // Chains the request handling logic, delegating to the controller's handle_find_context_context function.
        .and_then(controller::handle_find_context_context)
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
