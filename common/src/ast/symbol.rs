use crate::ast::{ast_graph::ScopeGraph, text_range::TextRange};

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Symbol {
    pub kind: String,
    pub range: TextRange,
    //pub relative_path: String,
    pub is_global: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SymbolMetaData {
    // variable name of the symbol
    pub symbol: String,
    // symbol type based on the language (Struct, function, etc.)
    pub symbol_type: String,
    // language id
    pub language_id: String,
    // repo name
    pub repo_name: String,
    pub relative_path: String,
    pub range: TextRange,
    //pub relative_path: String,
    pub is_global: bool,
    pub node_kind: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct SymbolKey {
    // variable name of the symbol
    pub symbol: String,
    // repo name
    pub repo_name: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SymbolValue {
    // symbol type based on the language (Struct, function, etc.)
    pub symbol_type: String,
    // language id
    pub language_id: String,
    // whether the symbol is defined in the root scope of the file or not.
    pub is_global: bool,
    // relative path of the file in which the symbol is defined
    pub relative_path: String,
    // range of the symbol in the file
    pub start_byte: usize,
    pub end_byte: usize,
    pub node_kind: String,
}

use std::collections::HashMap;

pub type SymbolMap = HashMap<SymbolKey, SymbolValue>;

/// Collection of symbol locations for *single* file
#[derive(Default, Debug, Clone, Deserialize, Serialize)]
#[non_exhaustive]
pub enum SymbolLocations {
    /// tree-sitter powered symbol-locations (and more!)
    TreeSitter(ScopeGraph),

    /// no symbol-locations for this file
    #[default]
    Empty,
}

impl SymbolLocations {
    pub fn list(&self) -> Vec<Symbol> {
        match self {
            Self::TreeSitter(graph) => graph.symbols(),
            Self::Empty => Vec::new(),
        }
    }

    pub fn list_metadata(
        &self,
        src: &[u8],
        repo_name: &str,
        language_id: &str,
        relative_path: &str,
    ) -> Vec<SymbolMetaData> {
        match self {
            Self::TreeSitter(graph) => graph.symbols_metadata(
                src,
                repo_name.to_string(),
                language_id.to_string(),
                relative_path.to_string(),
            ),
            Self::Empty => Vec::new(),
        }
    }

    pub fn scope_graph(&self) -> Option<&ScopeGraph> {
        match self {
            Self::TreeSitter(graph) => Some(graph),
            Self::Empty => None,
        }
    }
}
