use super::models::{CodeIndexingRequest, CodeIndexingStatus};
use ingestion::state::{get_process_state, queue_process, CodeIndexingTaskStatus};
use ingestion::{Config, Indexer};
use std::{convert::Infallible, env, path::PathBuf};

pub async fn handle_code_index_wrapper(
    request: CodeIndexingRequest,
) -> Result<impl warp::Reply, Infallible> {
    log::info!("Received code indexing request: {:?}", request);

    match handle_code_index_core(request).await {
        Ok(status) => Ok(warp::reply::with_status(
            warp::reply::json(&status),
            warp::http::StatusCode::OK,
        )),
        Err(e) => {
            log::error!("Background task failed: {}", e);
            Ok(warp::reply::with_status(
                warp::reply::json(&e.to_string()),
                warp::http::StatusCode::INTERNAL_SERVER_ERROR,
            ))
        }
    }
}

// TODO: Currently the underlying lib.rs functions don't do error propagation.
// Rather it just logs and moves on, in the essence it doesn't fail the indexing jobs.
// We need to refactor the underlying functions to handle the errors properly between
// ignorable and non-ignorable errors. So the task will never be in a failed state but
// in a completed state although the data might be corrupt.
async fn handle_code_index_core(
    request: CodeIndexingRequest,
) -> Result<CodeIndexingStatus, anyhow::Error> {
    log::info!("Code indexing request received: {:?}", request);

    let repo_name = request.repo_name.clone();
    let disk_path_str = request.repo_path.clone();
    let qdrant_url = env::var("QDRANT_URL").unwrap();
    let quickwit_url = env::var("QUICKWIT_URL").unwrap();
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

    let task_id = uuid::Uuid::new_v4().to_string();
    queue_process(&task_id, &repo_name, &disk_path_str);

    // Clone `task_id` for use in the asynchronous block
    let task_id_for_async = task_id.clone();

    // Use the indexer to index the repository, passing the disk path.
    tokio::spawn(async move {
        let _ = indexer
            .index_repository(
                disk_path,
                repo_name.to_string(),
                config,
                &branch,
                &version,
                task_id_for_async,
            )
            .await;
    });

    log::info!("Code indexing completed successfully");

    Ok(CodeIndexingStatus {
        repo_name: request.repo_name,
        repo_path: request.repo_path,
        task_id,
        task_status: CodeIndexingTaskStatus::Queued,
    })
}

pub async fn handle_index_status_wrapper(task_id: String) -> Result<impl warp::Reply, Infallible> {
    log::info!(
        "Received code indexing status request for task_id: {}",
        task_id
    );

    match handle_index_status_core(task_id).await {
        Ok(status) => Ok(warp::reply::with_status(
            warp::reply::json(&status),
            warp::http::StatusCode::OK,
        )),
        Err(e) => Ok(warp::reply::with_status(
            warp::reply::json(&e.to_string()),
            warp::http::StatusCode::INTERNAL_SERVER_ERROR,
        )),
    }
}

pub async fn handle_index_status_core(
    task_id: String,
) -> Result<CodeIndexingStatus, anyhow::Error> {
    match get_process_state(&task_id) {
        Some(state) => Ok(CodeIndexingStatus {
            repo_name: state.repo_name.clone(),
            repo_path: state.repo_path.clone(),
            task_id: task_id.clone(),
            task_status: state.task_status.clone(),
        }),
        None => return Err(anyhow::anyhow!("No task found for id {}", task_id)),
    }
}
