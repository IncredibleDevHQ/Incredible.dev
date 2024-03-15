use std::ops::Range;

use crate::CodeUnderstandings;

#[derive(serde::Serialize, serde::Deserialize, Clone, Debug, PartialEq)]
pub struct GenerateQuestionRequest {
    pub issue_desc: String,
    pub repo_name: String,
}

// Used to get code chunks given the repo, branch, path, range and id.
#[derive(serde::Serialize, serde::Deserialize, Clone, Debug, PartialEq)]
pub struct CodeSpanRequest {
    pub repo: String,
    pub branch: Option<String>,
    pub path: String,
    // text range of the code chunk from the file to extract
    pub ranges: Option<Vec<Range<usize>>>,
    pub id: Option<String>,
}

#[derive(serde::Serialize, serde::Deserialize, Clone, Debug, PartialEq)]
pub struct CodeUnderstandRequest {
    pub query: String,
    pub repo: String,
}

#[derive(serde::Serialize, serde::Deserialize, Clone, Debug, PartialEq)]
pub struct CodeContextRequest {
    // Contains the detailed code understandings and issue description to be processed.
    pub qna_context: CodeUnderstandings,
}