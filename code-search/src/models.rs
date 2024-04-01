use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
pub struct SymbolSearchRequest {
    pub query: String,
    pub repo_name: String,
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