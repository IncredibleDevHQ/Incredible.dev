use std::convert::Infallible;

use crate::models::SuggestRequest;

pub async fn handle_modify_code_wrapper(
    request: SuggestRequest,
) -> Result<impl warp::Reply, Infallible> {
    // TODO: Implement this function
    Ok(warp::reply::json(&request))
}
