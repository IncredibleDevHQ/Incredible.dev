use serde::{Deserialize, Serialize};

/// Represents a code chunk
#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct CodeChunk {
    pub path: String,
    #[serde(rename = "snippet")]
    pub snippet: String,
    #[serde(rename = "start")]
    pub start_line: usize,
    #[serde(rename = "end")]
    pub end_line: usize,
}

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
pub struct SymbolSearchRequest {
    pub query: String,
    pub repo_name: String,
}
