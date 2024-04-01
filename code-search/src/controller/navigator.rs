use std::{convert::Infallible, sync::Arc};

use anyhow::Result;
use common::{ast::graph_code_pluck::ContentDocument, TokenInfoRequest};
use reqwest::StatusCode;

use crate::{
    code_navigation::{CodeNavigationContext, FileSymbols, Token},
    snippet::Snipper,
    AppState,
};

pub async fn handle_token_info_fetcher_wrapper(
    request: TokenInfoRequest,
    app_state: Arc<AppState>,
) -> anyhow::Result<impl warp::Reply, Infallible> {
    match handle_token_info_fetcher(request, app_state).await {
        Ok(response) => Ok(warp::reply::with_status(
            warp::reply::json(&response),
            StatusCode::OK,
        )),
        Err(e) => {
            log::error!("Error processing modify code request: {}", e);
            // TODO: Convert the error message into a structured error response
            let error_message = format!("Error processing request: {}", e);
            Ok(warp::reply::with_status(
                warp::reply::json(&error_message),
                StatusCode::INTERNAL_SERVER_ERROR,
            ))
        }
    }
}

async fn handle_token_info_fetcher(
    request: TokenInfoRequest,
    app_state: Arc<AppState>,
) -> Result<Vec<FileSymbols>, anyhow::Error> {
    Ok(vec![])
}
