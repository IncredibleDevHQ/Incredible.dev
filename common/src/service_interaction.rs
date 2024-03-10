use crate::CodeChunk;

use super::CodeSpanRequest;
use anyhow::{anyhow, Error, Result};
use reqwest::{self, StatusCode};
use serde_json::Value; // Ensure this is accessible, either defined here or imported.

// Async function to fetch a specific span of code from a service.
// search_service_url: The URL of the search service where the code span should be fetched from.
// request: The data required by the search service to find and return the desired code span, encapsulated in a CodeSpanRequest struct.
pub async fn fetch_code_span(
    search_service_url: String,
    request: CodeSpanRequest,
) -> Result<Vec<CodeChunk>, Error> {
    // Create a new HTTP client instance. This client will be used to make the HTTP request.
    let client = reqwest::Client::new();

    log::debug!(
        "Fetching code span from {} with request: {:?}",
        search_service_url,
        request
    );

    // Send the POST request to the search_service_url with the JSON-serialized CodeSpanRequest.
    let response = client
        .post(search_service_url)
        .json(&request)
        .send()
        .await?;

    match response.status() {
        // Handle successful responses (200-299).
        StatusCode::OK => {
            let res: Value = response.json::<Value>().await?;
            log::debug!("Received successful response for code span: {:?}", res);

            // TODO: Send the deserialize error in a more structured way.
            let code_chunks = serde_json::from_value::<Vec<CodeChunk>>(res.clone())
                .map_err(|e| anyhow!("Failed to deserialize code chunks: {}", e))?;
            Ok(code_chunks)
        }
        // Handle client errors (400-499).
        StatusCode::BAD_REQUEST
        | StatusCode::UNAUTHORIZED
        | StatusCode::FORBIDDEN
        | StatusCode::NOT_FOUND
        | StatusCode::METHOD_NOT_ALLOWED => {
            let error_message = format!("Client error: {}", response.status());
            log::error!("{}", error_message);
            Err(anyhow!(error_message))
        }
        // Handle server errors (500-599).
        StatusCode::INTERNAL_SERVER_ERROR
        | StatusCode::BAD_GATEWAY
        | StatusCode::SERVICE_UNAVAILABLE
        | StatusCode::GATEWAY_TIMEOUT => {
            let error_message = format!("Server error: {}", response.status());
            log::error!("{}", error_message);
            Err(anyhow!(error_message))
        }
        // Handle any other statuses.
        _ => {
            let error_message = format!("Unexpected HTTP response: {}", response.status());
            log::error!("{}", error_message);
            Err(anyhow!(error_message))
        }
    }
}
