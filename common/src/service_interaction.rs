use std::collections::HashMap;

use crate::{models::CodeSpanRequest, CodeChunk};

use anyhow::{anyhow, Error, Result};
use reqwest::{self, Client, Method, StatusCode, Url};
use serde::{de::DeserializeOwned, Serialize};
use serde_json::{json, Value}; // Ensure this is accessible, either defined here or imported.

// Async function to fetch a specific span of code from a service.
// search_service_url: The URL of the search service where the code span should be fetched from.
// request: The data required by the search service to find and return the desired code span, encapsulated in a CodeSpanRequest struct.
pub async fn fetch_code_span(
    search_service_url: String,
    request: CodeSpanRequest,
) -> Result<Vec<CodeChunk>, Error> {
    // Create a new HTTP client instance. This client will be used to make the HTTP request.
    let client = Client::new();

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

// Async function to call a service and return the response as a deserialized object.
pub async fn service_caller<A: Serialize, B: DeserializeOwned>(
    url: String,
    method: Method,
    body: Option<A>,
    query_params: Option<HashMap<String, String>>,
) -> Result<B, Error> {
    // Parse the URL to ensure it's valid
    let url = Url::parse(&url).map_err(|e| anyhow!("Invalid URL: {}", e))?;

    // Create a new HTTP client instance
    let client = Client::new();

    log::debug!("Calling service at {} with method {:?}", url, method);

    // Prepare the request with the specified method
    let mut request_builder = client.request(method.clone(), url);

    // Add query parameters if present
    if let Some(params) = query_params {
        request_builder = request_builder.query(&params);
    }

    // If there is a body, serialize it to JSON and attach it to the request.
    if let Some(body_value) = body {
        if method != Method::GET {
            let json_body = json!(body_value);
            request_builder = request_builder.json(&json_body);
        } else {
            log::warn!("Body provided for a GET request will be ignored.");
        }
    }

    let response = request_builder.send().await?;

    // General response handling
    match response.status() {
        StatusCode::OK => {
            let res: Value = response.json::<Value>().await?;
            log::debug!("Received successful response: {:?}", res);

            let res_obj = serde_json::from_value::<B>(res.clone())
                .map_err(|e| anyhow!("Failed to deserialize: {}", e))?;
            Ok(res_obj)
        }
        StatusCode::BAD_REQUEST
        | StatusCode::UNAUTHORIZED
        | StatusCode::FORBIDDEN
        | StatusCode::NOT_FOUND
        | StatusCode::METHOD_NOT_ALLOWED
        | StatusCode::INTERNAL_SERVER_ERROR
        | StatusCode::BAD_GATEWAY
        | StatusCode::SERVICE_UNAVAILABLE
        | StatusCode::GATEWAY_TIMEOUT => {
            let error_message = format!("Error: Response status: {}, Error Message: {}", response.status(), response.text().await?);
            log::error!("{}", error_message);
            Err(anyhow!(error_message))
        }
        _ => {
            let error_message = format!("Unexpected HTTP response: {}", response.status());
            log::error!("{}", error_message);
            Err(anyhow!(error_message))
        }
    }
}
