use crate::models::ParentScopeRequest;
use crate::search::code_search::get_file_content;

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
                let code_file =content_doc.content.clone();

                // Deserialize the symbol locations embedded in the source document.
                let symbol_locations = content_doc.symbol_locations();

                if symbol_locations.is_ok() {
                    // If no symbol locations are found, construct a NOT FOUND response.
                    let response = format!("Error Deserializing the scope binary : {}", path);
                    Ok(warp::reply::with_status(
                        warp::reply::json(&response),
                        warp::http::StatusCode::INTERNAL_SERVER_ERROR,
                    ))
                } 

                let scope_binary = symbol_locations.unwrap();
                let line_end_indices: Vec<usize> = content_doc.fetch_line_indices(); 

                let scope = scope_binary.get_scope(params.start_line, params.end_line);

                // if both start and end line are missing, send the entire content
                    Ok(warp::reply::with_status(
                        warp::reply::json(&code_file),
                        warp::http::StatusCode::OK,
                    ))
                    // Convert the compacted u8 array of line end indices back to their original u32 format.
                    // let line_end_indices = content_doc.fetch_line_indices(); 

                    // // pluck the code chunk from the source code file content.
                    // let code_chunk = pluck_code_by_lines(
                    //     &code_file,
                    //     &line_end_indices,
                    //     params.start_line,
                    //     params.end_line,
                    // );

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
