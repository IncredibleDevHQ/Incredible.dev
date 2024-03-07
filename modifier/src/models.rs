use std::ops::Range;
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
    pub user_query: String,
    pub assistant_query: String,
    pub context_files: Vec<ContextFile>,
}

#[derive(serde::Serialize, serde::Deserialize, Clone, Debug, PartialEq)]
pub struct ContextFile {
    pub path: String,
    pub hidden: bool,
    pub repo: String,
    pub branch: Option<String>,
    pub ranges: Vec<Range<usize>>,
}
