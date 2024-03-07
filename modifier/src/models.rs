use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, serde::Serialize, serde::Deserialize)]
pub enum FileChangeStatus {
    #[serde(rename = "added")]
    Added,
    #[serde(rename = "removed")]
    Removed,
    #[serde(rename = "modified")]
    Modified,
    #[serde(rename = "renamed")]
    Renamed,
    #[serde(rename = "copied")]
    Copied,
    #[serde(rename = "changed")]
    Changed,
    #[serde(rename = "unchanged")]
    Unchanged,
}

#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct FileChange {
    #[serde(rename = "path")]
    pub path: String,
    #[serde(rename = "status")]
    pub status: FileChangeStatus,
    #[serde(rename = "patch")]
    pub patch: String,
    #[serde(rename = "previous_filename")]
    pub previous_filename: Option<String>,
}

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
pub struct CodeModifierRequest {
    pub query: String,
    pub repo_name: String,
    pub file_paths: Vec<String>,
}
