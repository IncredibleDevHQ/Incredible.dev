use petgraph::{graph::NodeIndex, visit::EdgeRef, Direction};
use serde::{Deserialize, Serialize};

use super::{
    scope_graph::{EdgeKind, ScopeGraph},
    symbol::{SymbolId, TextRange},
};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, Hash)]
pub struct LocalDef {
    pub range: TextRange,
    pub symbol_id: Option<SymbolId>,
}

impl LocalDef {
    /// Initialize a new definition
    pub fn new(range: TextRange, symbol_id: Option<SymbolId>) -> Self {
        Self { range, symbol_id }
    }

    pub fn name<'a>(&self, buffer: &'a [u8]) -> &'a [u8] {
        &buffer[self.range.start.byte..self.range.end.byte]
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, Hash)]
pub struct LocalImport {
    pub range: TextRange,
}

impl LocalImport {
    /// Initialize a new import
    pub fn new(range: TextRange) -> Self {
        Self { range }
    }

    pub fn name<'a>(&self, buffer: &'a [u8]) -> &'a [u8] {
        &buffer[self.range.start.byte..self.range.end.byte]
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Reference {
    pub range: TextRange,
    pub symbol_id: Option<SymbolId>,
}

impl Reference {
    /// Initialize a new reference
    pub fn new(range: TextRange, symbol_id: Option<SymbolId>) -> Self {
        Self { range, symbol_id }
    }

    pub fn name<'a>(&self, buffer: &'a [u8]) -> &'a [u8] {
        &buffer[self.range.start.byte..self.range.end.byte]
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
pub struct LocalScope {
    pub range: TextRange,
}

impl LocalScope {
    pub fn new(range: TextRange) -> Self {
        Self { range }
    }
}

pub struct ScopeStack<'a> {
    pub scope_graph: &'a ScopeGraph,
    pub start: Option<NodeIndex<u32>>,
}

impl<'a> Iterator for ScopeStack<'a> {
    type Item = NodeIndex<u32>;
    fn next(&mut self) -> Option<Self::Item> {
        if let Some(start) = self.start {
            let parent = self
                .scope_graph
                .graph
                .edges_directed(start, Direction::Outgoing)
                .find(|edge| *edge.weight() == EdgeKind::ScopeToScope)
                .map(|edge| edge.target());
            let original = start;
            self.start = parent;
            Some(original)
        } else {
            None
        }
    }
}

/// A grouping of symbol kinds that allow references among them.
/// A variable can refer only to other variables, and not types, for example.
pub type NameSpace = &'static [&'static str];

/// A collection of namespaces
pub type NameSpaces = &'static [NameSpace];

// Helper trait
pub trait NameSpaceMethods {
    fn all_symbols(self) -> Vec<&'static str>;

    fn symbol_id_of(&self, symbol: &str) -> Option<SymbolId>;
}

impl NameSpaceMethods for NameSpaces {
    fn all_symbols(self) -> Vec<&'static str> {
        self.iter().flat_map(|ns| ns.iter().cloned()).collect()
    }

    fn symbol_id_of(&self, symbol: &str) -> Option<SymbolId> {
        self.iter()
            .enumerate()
            .find_map(|(namespace_idx, namespace)| {
                namespace
                    .iter()
                    .position(|s| s == &symbol)
                    .map(|symbol_idx| SymbolId {
                        namespace_idx,
                        symbol_idx,
                    })
            })
    }
}
