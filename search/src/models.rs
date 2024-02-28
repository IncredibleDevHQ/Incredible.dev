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

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
pub struct SpanSearchRequest {
    pub repo: String,
    pub branch: Option<String>,
    pub path: String,
    // text range of the code chunk from the file to extract
    pub start: Option<usize>,
    pub end: Option<usize>,
    // optional uid to track the request
    pub id: Option<String>,
}


/// Represents a request to fetch the parent scope of a specified code range within a file.
#[derive(Clone, Debug, Default, Deserialize, Serialize)]
pub struct ParentScopeRequest {
    /// The repository containing the target file.
    pub repo: String,
    /// The file path within the repository.
    pub file: String,
    /// The starting line number of the code range.
    pub start_line: usize,
    /// The ending line number of the code range.
    pub end_line: usize,
    /// An optional identifier for the request, which can be used for tracking or caching.
    pub id: Option<String>,
}