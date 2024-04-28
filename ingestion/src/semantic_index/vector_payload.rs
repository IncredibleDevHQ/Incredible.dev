use std::collections::HashMap;
use qdrant_client::prelude::Value;

use common::tokenizer_onnx::Embedding;

// Payload format to write and deserialize data in and from qdrant.
#[derive(Default, Clone, Debug, serde::Deserialize, serde::Serialize)]
pub struct SymbolPayload {

    pub repo_name: String,
    pub symbol: String,

    pub symbol_types: Vec<String>,
    pub lang_ids: Vec<String>,
    pub is_globals: Vec<bool>, 
    pub start_bytes: Vec<i64>,
    pub end_bytes: Vec<i64>,
    pub relative_paths: Vec<String>,
    pub node_kinds: Vec<String>,

    #[serde(skip)]
    pub id: Option<String>,
    #[serde(skip)]
    pub embedding: Option<Embedding>,
    #[serde(skip)]
    pub score: Option<f32>,
}

impl SymbolPayload {
    pub fn convert_to__qdrant_fields(self) -> HashMap<String, Value> {
        HashMap::from([
            ("repo_name".into(), self.repo_name.into()),
            ("symbol".into(), self.symbol.into()),

            ("lang".into(), self.lang_ids.into()),
            ("symbol_type".into(), self.symbol_types.into()),
            ("start_byte".into(), self.start_bytes.into()),
            ("end_byte".into(), self.end_bytes.into()),
            ("relative_path".into(), self.relative_paths.into()),
            ("node_kind".into(), self.node_kinds.into()),
            ("is_global".into(), self.is_globals.into()),
        ])
    }
}

#[derive(Default, Clone, Debug, serde::Deserialize, serde::Serialize)]
pub struct Payload {
    pub lang: String,
    pub repo_name: String,
    pub repo_ref: String,
    pub relative_path: String,
    pub content_hash: String,
    pub text: String,
    pub start_line: u64,
    pub end_line: u64,
    pub start_byte: u64,
    pub end_byte: u64,
    pub branches: Vec<String>,

    #[serde(skip)]
    pub id: Option<String>,
    #[serde(skip)]
    pub embedding: Option<Embedding>,
    #[serde(skip)]
    pub score: Option<f32>,
}

impl Payload {
    pub fn convert_to__qdrant_fields(self) -> HashMap<String, Value> {
        HashMap::from([
            ("lang".into(), self.lang.to_ascii_lowercase().into()),
            ("repo_name".into(), self.repo_name.into()),
            ("relative_path".into(), self.relative_path.into()),
            ("content_hash".into(), self.content_hash.into()),
            ("snippet".into(), self.text.into()),
            ("start_line".into(), self.start_line.to_string().into()),
            ("end_line".into(), self.end_line.to_string().into()),
            ("start_byte".into(), self.start_byte.to_string().into()),
            ("end_byte".into(), self.end_byte.to_string().into()),
        ])
    }
}
impl PartialEq for Payload {
    fn eq(&self, other: &Self) -> bool {
        self.lang == other.lang
            && self.repo_name == other.repo_name
            && self.repo_ref == other.repo_ref
            && self.relative_path == other.relative_path
            && self.content_hash == other.content_hash
            && self.text == other.text
            && self.start_line == other.start_line
            && self.end_line == other.end_line
            && self.start_byte == other.start_byte
            && self.end_byte == other.end_byte
            && self.branches == other.branches
        // ignoring deserialized fields that will not exist on a newly
        // created payload
    }
}
