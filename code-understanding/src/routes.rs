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
        .or(task_list(app_state.clone()))
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

/// POST /task-list
/// # Request Body
/// The request body should contain a JSON object with two fields:
/// - `issue_desc`: A string describing the issue for which tasks and subtasks need to be generated.
/// - `repo_name`: A string representing the name of the repository where the issue resides.
///
/// Example JSON body:
/// ```json
/// {
///     "issue_desc": "I want to modify the API inside orchestor service, make it call the code-understanding service API, and then for each question returned, I would like to call another API from the same service to obtain answers",
///     "repo_name": "nezuko-ai"
/// }
/// ```
///
/// # Responses
/// - Returns a `warp::Reply` on success, indicating that the tasks and associated questions have been successfully generated and returned.
/// - Returns a `warp::Rejection` in case of errors during request processing.

// Example JSON response body"
// {
//     "tasks": [
//       {
//         "task": "Modify the API inside Orchestor Service to call the Code-Understanding Service API",
//         "subtasks": [
//           {
//             "subtask": "Investigate current behavior of Orchestor Service when it's calling other APIs",
//             "questions": [
//               "How does the Orchestor Service currently handle API calls?",
//               "Does the Orchestor Service currently call the Code-Understanding Service API?"
//             ]
//           },
//           {
//             "subtask": "Modify the Orchestor Service to call the Code-Understanding Service API",
//             "questions": [
//               "How should the Orchestor Service be changed to incorporate the Code-Understanding Service API call?",
//               "What data is required to make the Code-Understanding Service API call successfully?"
//             ]
//           }
//         ]
//       },
//       {
//         "task": "Modify the Orchestor Service API to call another API for processing questions obtained from the Code-Understanding Service API",
//         "subtasks": [
//           {
//             "subtask": "Analyze the current handling of obtained questions from Code-Understanding Service API",
//             "questions": [
//               "How are the obtained questions from the Code-Understanding Service API currently being handled?",
//               "What is the existing procedure for processing these questions in the Orchestor Service?"
//             ]
//           },
//           {
//             "subtask": "Implement functionalities to process each question obtained from the Code-Understanding Service API using another API from the Orchestor Service",
//             "questions": [
//               "How to ensure the correct matching of each question to its corresponding API call within the Orchestor Service?",
//               "What are the potential challenges in updating Orchestor Service to process the questions with another API call?"
//             ]
//           }
//         ]
//       }
//     ]
//   }
fn task_list(
    app_state: Arc<AppState>,
) -> impl Filter<Extract = impl warp::Reply, Error = warp::Rejection> + Clone {
    warp::path("task-list")
        .and(warp::post())
        .and(warp::body::json())
        .and(warp::any().map(move || app_state.clone()))
        .and_then(controller::generate_task_list)
}
