extern crate tree_sitter;
extern crate once_cell;
use once_cell::sync::OnceCell;
use serde::{Deserialize, Serialize};


mod c;
mod c_sharp;
mod cpp;
mod go;
mod java;
mod javascript;
mod php;
mod python;
mod r;
mod ruby;
mod rust;
mod typescript;


#[cfg(test)]
mod test_utils;


pub enum Language<Config: 'static> {
    /// A supported language, with some `Config`.
    Supported(&'static Config),

    /// An unsupported language
    Unsupported,
}

pub struct TSLanguageConfig {
    /// A list of language names that can be processed by these scope queries
    /// e.g.: ["Typescript", "TSX"], ["Rust"]
    pub language_ids: &'static [&'static str],

    /// Extensions that can help classify the file: .rs, .rb, .cabal
    pub file_extensions: &'static [&'static str],

    /// tree-sitter grammar for this language
    pub grammar: fn() -> tree_sitter::Language,

    /// Compiled tree-sitter scope query for this language.
    pub scope_query: MemoizedQuery,

    /// Compiled tree-sitter hoverables query
    pub hoverable_query: MemoizedQuery,

    /// Namespaces defined by this language,
    /// E.g.: type namespace, variable namespace, function namespace
    pub namespaces: NameSpaces,
}

#[derive(Debug)]
pub struct MemoizedQuery {
    slot: OnceCell<tree_sitter::Query>,
    scope_query: &'static str,
}

impl MemoizedQuery {
    pub const fn new(scope_query: &'static str) -> Self {
        Self {
            slot: OnceCell::new(),
            scope_query,
        }
    }

    /// Get a reference to the relevant tree sitter compiled query.
    ///
    /// This method compiles the query if it has not already been compiled.
    pub fn query(
        &self,
        grammar: fn() -> tree_sitter::Language,
    ) -> Result<&tree_sitter::Query, tree_sitter::QueryError> {
        self.slot
            .get_or_try_init(|| tree_sitter::Query::new(grammar(), self.scope_query))
    }
}


pub type TSLanguage = Language<TSLanguageConfig>;

impl TSLanguage {
    /// Find a tree-sitter language configuration from a language identifier
    ///
    /// See [0] for a list of valid language identifiers.
    ///
    /// [0]: https://github.com/monkslc/hyperpolyglot/blob/master/src/codegen/languages.rs
    pub fn from_id(lang_id: &str) -> Self {
        ALL_LANGUAGES
            .iter()
            .copied()
            .find(|target| {
                target
                    .language_ids
                    .iter()
                    .any(|&id| id.to_lowercase() == lang_id.to_lowercase())
            })
            .map_or(Language::Unsupported, Language::Supported)
    }
}

pub static ALL_LANGUAGES: &[&TSLanguageConfig] = &[
    &c::C,
    &go::GO,
    &javascript::JAVASCRIPT,
    &python::PYTHON,
    &rust::RUST,
    &typescript::TYPESCRIPT,
    &c_sharp::C_SHARP,
    &java::JAVA,
    &cpp::CPP,
    &ruby::RUBY,
    &r::R,
    &php::PHP,
];


/// An opaque identifier for every symbol in a language
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, Hash)]
pub struct SymbolId {
    pub namespace_idx: usize,
    pub symbol_idx: usize,
}

impl SymbolId {
    pub fn name(&self, namespaces: NameSpaces) -> &'static str {
        namespaces[self.namespace_idx][self.symbol_idx]
    }
}

/// A grouping of symbol kinds that allow references among them.
/// A variable can refer only to other variables, and not types, for example.
pub type NameSpace = &'static [&'static str];

/// A collection of namespaces
pub type NameSpaces = &'static [NameSpace];

/// Helper trait
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