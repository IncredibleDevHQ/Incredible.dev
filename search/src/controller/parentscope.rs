use crate::models::ParentScopeRequest;

pub fn parent_scope_search(
    params: ParentScopeRequest,
) -> Result<impl warp::Reply, warp::Rejection> {
    // return empty ok response  with ok(wrap::reply::json(&"")) if no params found
    Ok(warp::reply::json(&""))
}
