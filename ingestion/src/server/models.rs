use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct CodeIndexingRequest {
    pub repo_name: String,
    #[serde(default = "default_repo_path")]
    pub repo_path: String,
    #[serde(default = "default_branch")]
    pub branch: String,
    // TODO: Change the version to be a float instead of a string
    #[serde(default = "default_version")]
    pub version: String,
}

fn default_repo_path() -> String {
    String::from("path/to/repo")
}

fn default_branch() -> String {
    String::from("main")
}

fn default_version() -> String {
    String::from("v1")
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct CodeIndexingStatus {
    pub repo_name: String,
    pub repo_path: String,
    pub task_id: String,
    pub task_status: CodeIndexingTaskStatus,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub enum CodeIndexingTaskStatus {
    Queued,
    Running,
    Completed,
    Failed,
}
