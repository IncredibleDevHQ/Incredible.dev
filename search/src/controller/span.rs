use crate::models::SpanSearchRequest;
use crate::search::code_search::get_file_content;


/// Asynchronously handles a search request for a specific span within a file in a repository.
///
/// # Parameters
/// - `params`: An instance of `SpanSearchRequest` containing the necessary parameters to perform the search.
///
/// # Returns
/// - An `Ok` variant of `Result` containing an `impl warp::Reply` that represents the HTTP response,
///   which varies based on the outcome of the file content retrieval.
pub async fn span_search(params: SpanSearchRequest) -> Result<impl warp::Reply, warp::Rejection> {
    // Clone necessary parameters from the request for local use.
    let path = params.path.clone();
    let repo_name = params.repo.clone();

    // Attempt to retrieve the file content asynchronously based on the provided path and repository name.
    let source_document = get_file_content(&path, &repo_name).await;

    match source_document {
        Ok(content) => {
            // Determine the response based on the content availability.
            if content.is_none() {
                // If no content is found, construct a NOT FOUND response.
                let response = format!("No content found for the file: {}", path);
                Ok(warp::reply::with_status(
                    warp::reply::json(&response),
                    warp::http::StatusCode::NOT_FOUND,
                ))
            } else {
                // If content is found, construct an OK response with the content.
                let response = format!("Content: {:?}", content.unwrap());
                Ok(warp::reply::with_status(
                    warp::reply::json(&response),
                    warp::http::StatusCode::OK,
                ))
            }
        },
        Err(e) => {
            // If an error occurs during content retrieval, construct an INTERNAL SERVER ERROR response.
            let response = format!("Error: {}", e);
            Ok(warp::reply::with_status(
                warp::reply::json(&response),
                warp::http::StatusCode::INTERNAL_SERVER_ERROR,
            ))
        }
    }
}
