use std::ops::Range;

#[derive(serde::Serialize, serde::Deserialize, Clone, Debug, PartialEq)]
pub struct CodeContext {
    pub path: String,
    pub hidden: bool,
    pub repo: String,  // Ensure RepoRef is accessible or defined here.
    pub branch: Option<String>,
    pub ranges: Vec<Range<usize>>,
}
