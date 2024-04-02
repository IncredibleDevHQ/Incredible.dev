use std::{convert::Infallible, sync::Arc};

use anyhow::{anyhow, Result};
use common::{
    ast::graph_code_pluck::ContentDocument, hasher::generate_quikwit_index_name, TokenInfoRequest,
};
use reqwest::StatusCode;

use crate::{
    code_navigation::{CodeNavigationContext, FileSymbols, Token},
    search::{code_search::get_file_content, quikwit::get_all_files_for_repo},
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
    let source_document = match get_file_content(
        &request.relative_path.clone(),
        &request.repo_ref.clone(),
        app_state.clone(),
    )
    .await
    {
        Ok(Some(doc)) => doc,
        Ok(None) => return Err(anyhow!("No document found")),
        Err(e) => {
            return Err(anyhow::Error::from(e));
        }
    };

    let all_docs = match get_all_files_for_repo(
        &generate_quikwit_index_name(&request.repo_ref.clone()),
        &request.repo_ref.clone(),
        app_state.clone(),
    )
    .await
    {
        Ok(docs) => docs,
        Err(e) => {
            return Err(anyhow!("Failed to fetch all files: {}", e));
        }
    };

    match get_token_info(
        request.clone(),
        request.repo_ref.clone(),
        &source_document,
        &all_docs,
        Some(0),
        Some(0),
    )
    .await
    {
        Ok(content) => {
            log::debug!(
                "Token info fetched successfully: {}",
                serde_json::to_string(&content)?
            );
            return Ok(content);
        }
        Err(e) => return Err(anyhow::anyhow!("failed to fetch source content: {}", e)),
    }
}

pub async fn get_token_info(
    params: TokenInfoRequest,
    repo_ref: String,
    source_doc: &ContentDocument,
    all_docs: &Vec<ContentDocument>,
    context_before: Option<usize>, // This will be None
    context_after: Option<usize>,  // This will be None
) -> anyhow::Result<Vec<FileSymbols>> {
    let source_document_idx = all_docs
        .iter()
        .position(|doc| doc.relative_path == source_doc.relative_path)
        .ok_or(anyhow::anyhow!("invalid language"))?;

    let snipper =
        Some(Snipper::default().context(context_before.unwrap_or(0), context_after.unwrap_or(0)));

    let ctx: CodeNavigationContext<'_, '_> = CodeNavigationContext {
        token: Token {
            repo: repo_ref.clone(),
            relative_path: params.relative_path.as_str(),
            start_byte: params.start,
            end_byte: params.end,
        },
        all_docs,
        source_document_idx,
        snipper,
    };

    let data = ctx.token_info();
    if data.is_empty() {
        // search_nav(
        //     repo_ref,
        //     ctx.active_token_text(),
        //     ctx.active_token_range(),
        //     params.branch.as_deref(),
        //     source_doc,
        //     snipper,
        // )
        // .await
        Ok(data)
    } else {
        Ok(data)
    }
}
