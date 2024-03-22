use tokio::fs::File;
use anyhow::{Result, Error};
use common::{models::TaskListResponse, CodeUnderstanding};
use tokio::io::AsyncReadExt;
use std::path::Path;
use common::models::TaskList;
use crate::task_graph::graph_model::QuestionWithAnswer;


// Define an asynchronous function to read and deserialize the JSON data.
pub async fn read_code_understanding_from_file<P: AsRef<Path>>(path: P) -> Result<Vec<QuestionWithAnswer>> {
    let mut file = File::open(path).await?;
    let mut data = String::new();
    file.read_to_string(&mut data).await?;
    let code_understanding: Vec<QuestionWithAnswer> = serde_json::from_str(&data)?;
    Ok(code_understanding)
}

pub async fn read_task_list_from_file<P: AsRef<Path>>(path: P) -> Result<TaskListResponse> {
    let mut file = File::open(path).await?;
    let mut data = String::new();
    file.read_to_string(&mut data).await?;
    let task_list: TaskListResponse = serde_json::from_str(&data)?;
    Ok(task_list)
}
