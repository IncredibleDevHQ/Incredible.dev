use crate::routes;
use std::convert::Infallible;
use warp::{http::Response, http::StatusCode, Filter, Rejection, Reply};

pub async fn handle_retrieve_code(
    req: routes::RetrieveCodeRequest,
) -> Result<impl warp::Reply, Infallible> {
    println!("Query: {}, Repo: {}", req.query, req.repo);
    // Combine query and repo_name in the response
    let response = format!("Query: '{}', Repo: '{}'", req.query, req.repo);
    Ok(warp::reply::with_status(
        warp::reply::json(&response),
        StatusCode::OK,
    ))
    // Err(e) => Ok(warp::reply::with_status(
    //     warp::reply::json(&format!("Error: {}", e)),
    //     StatusCode::INTERNAL_SERVER_ERROR,
    // )),
}
