use crate::models::ParentScopeRequest;
use crate::search::code_search::{get_file_content, ExtractionConfig};
use crate::utilities::util::return_byte_range_from_line_numbers;
use anyhow::anyhow;

pub async fn parent_scope_search(
    params: ParentScopeRequest,
) -> Result<impl warp::Reply, warp::Rejection> {
    let path = params.file.clone();
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
                let content_doc = content.unwrap();
                let code_file = content_doc.content.clone();

                // Deserialize the symbol locations embedded in the source document.
                let symbol_locations = content_doc.symbol_locations();

                // if there is no symbol locations, return a BAD REQUEST response
                if symbol_locations.is_err() {
                    let response = format!("Error: No symbol locations found for the file: {}", path);
                    return Ok(warp::reply::with_status(
                        warp::reply::json(&response),
                        warp::http::StatusCode::BAD_REQUEST,
                    ));
                }

                let scope_binary = symbol_locations.unwrap();
                let line_end_indices: Vec<usize> = content_doc.fetch_line_indices();

                // get the byte range for the start and end line from params calling return_byte_range_from_lines
                let byte_range = return_byte_range_from_line_numbers(
                    &line_end_indices,
                    Some(params.start_line),
                    Some(params.end_line),
                );

                // if byte range has error return the error
                if byte_range.is_err() {
                    let response = format!("Error: {}", byte_range.err().unwrap());
                    return Ok(warp::reply::with_status(
                        warp::reply::json(&response),
                        warp::http::StatusCode::BAD_REQUEST,
                    ));
                }

                let (start_byte, end_byte) = byte_range.unwrap();

                // return bad request if scope graph cannot be found.
                // get scope graph from the symbol locations
                let sg = scope_binary
                    .scope_graph();

                // return HTTP bad request response from the api if scope graph cant be foud 
                if sg.is_none() {
                    let response = format!("Error: Scope graph not found for the file: {}", path);
                    return Ok(warp::reply::with_status(
                        warp::reply::json(&response),
                        warp::http::StatusCode::BAD_REQUEST,
                    ));
                }
                // extract scope graph from the Option after the validation that it exists
                let sg = sg.unwrap();

                let extraction_config = ExtractionConfig {
                    code_byte_expansion_range: 300,
                    min_lines_to_return: 8,
                    max_lines_limit: Some(200),
                };

                // Expands to the parent scope of the given byte range
                // if the scope is too small, it expands the scope to the code_byte_expansion_range specified in the extraction_config
                // if the scope is too large, it limits the scope to the max_lines_limit specified in the extraction_config
                // otherwise the scope is greater than the min_lines_to_return specified in the extraction_config
                // and smaller than the max_lines_limit specified in the extraction_config
                // we return the extracted content containing the code of the parent scope which contains the given line range
                let extract_content = sg.expand_scope(
                    &params.file,
                    start_byte,
                    end_byte,
                    &content_doc,
                    &line_end_indices,
                    &extraction_config,
                );

                // return the extracted content
                Ok(warp::reply::with_status(
                    warp::reply::json(&extract_content),
                    warp::http::StatusCode::OK,
                ))
            }
        }
        Err(e) => {
            // If an error occurs during code chunk retrieval, construct a BAD REQUEST response.
            let response = format!("Error: {}", e);
            Ok(warp::reply::with_status(
                warp::reply::json(&response),
                warp::http::StatusCode::BAD_REQUEST,
            ))
        }
    }
}
