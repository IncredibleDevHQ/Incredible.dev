use super::models::{CodeIndexingRequest, CodeIndexingStatus};
use crate::server::models::CodeIndexingTaskStatus;
use ingestion::{Config, Indexer};
use reqwest::StatusCode;
use std::{convert::Infallible, env, path::PathBuf};

pub async fn handle_code_index_wrapper(
    request: CodeIndexingRequest,
) -> Result<impl warp::Reply, Infallible> {
    // Clone data necessary for the background task
    let bg_request = request.clone();

    // Spawn a background task without awaiting its result
    tokio::spawn(async move {
        match handle_code_index_core(bg_request).await {
            Ok(_) => log::info!("Background task completed successfully"),
            Err(e) => log::error!("Background task failed: {}", e),
        }
    });

    // Immediately respond to the HTTP request
    Ok(warp::reply::with_status(
        warp::reply::json(&"Task started"),
        StatusCode::ACCEPTED,
    ))
}

async fn handle_code_index_core(
    request: CodeIndexingRequest,
) -> Result<CodeIndexingStatus, anyhow::Error> {
    log::info!("Code indexing request received: {:?}", request);

    let repo_name = request.repo_name.clone();
    let disk_path_str = request.repo_path.clone();
    let qdrant_url = env::var("QDRANT_URL").unwrap();
    let quickwit_url = env::var("QDRANT_URL").unwrap();
    let qdrant_api_key = env::var("QDRANT_API_KEY").unwrap();
    let branch = request.branch.clone();
    let version = request.version.clone();

    log::info!("Repo name: {}", repo_name);
    log::info!("Repo path: {}", disk_path_str);
    log::info!("Qdrant URL: {}", qdrant_url);
    log::info!("Quickwit URL: {}", quickwit_url);
    log::info!("Qdrant API key: {}", qdrant_api_key);
    log::info!("Branch: {}", branch);
    log::info!("Version: {}", version);

    // Instantiate an Indexer.
    let indexer = Indexer;

    // Create a disk path pointing to a valid Git repository.
    // let _ = tokio::task::spawn_blocking(move || {
    let disk_path = PathBuf::from(disk_path_str.clone());
    let config = Config::new(
        repo_name.to_string(),
        disk_path_str.to_string(),
        qdrant_url.to_string(),
        quickwit_url.to_string(),
        qdrant_api_key.to_string(),
        branch.to_string(),
        version.to_string(),
    );

    // Use the indexer to index the repository, passing the disk path.
    let _ = indexer
        .index_repository(disk_path, repo_name.to_string(), config, &branch, &version)
        .await;
    // })
    // .await?;

    log::info!("Code indexing completed successfully");

    Ok(CodeIndexingStatus {
        repo_name: request.repo_name,
        repo_path: request.repo_path,
        task_id: "1234567890".to_string(),
        task_status: CodeIndexingTaskStatus::Running,
    })
}
