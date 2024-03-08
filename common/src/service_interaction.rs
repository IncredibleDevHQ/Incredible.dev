use crate::CodeChunk;

use super::CodeSpanRequest;
use anyhow::{anyhow, Error, Result};
use reqwest;
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

    // Send a POST request to the search_service_url with the JSON-serialized CodeSpanRequest.
    let res: Value = client
        .post(search_service_url)
        .json(&request)
        .send()
        .await?
        .json::<Value>()
        .await?;

    // Check the "status" field in the response to determine if the operation was successful.
    // If the status is "success", retrieve the "content" field from the data object, which contains the requested code span.
    // If the status is not "success", or if any fields are missing, return an error with the description provided in the response or a default error message.
    match res["status"].as_str() {
        Some("success") => {
            let code_chunks = serde_json::from_value::<Vec<CodeChunk>>(res["data"].clone())
                .map_err(|e| anyhow!("Failed to deserialize code chunks: {}", e))?; // Use anyhow! to convert the error.
            Ok(code_chunks)
        }
        _ => Err(anyhow!(
            "Error fetching code span: {}",
            res.get("data")
                .and_then(|d| d["error"].as_str())
                .unwrap_or("Unknown error")
        )),
    }
}
