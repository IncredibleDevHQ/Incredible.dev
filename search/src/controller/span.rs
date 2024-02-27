use crate::models::SpanSearchRequest;

pub async fn span_search(params: SpanSearchRequest) -> Result<impl warp::Reply, warp::Rejection> {
    // TODO: Implement span search logic here. Placeholder implementation:
    Ok(warp::reply::json(&params))
}