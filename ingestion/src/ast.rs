use tree_sitter::{Parser, Tree};
pub mod ast_graph;
pub mod debug;
pub mod def;
pub mod import;
pub mod language_support;
pub mod reference;
pub mod scope;
pub mod symbol;
pub mod text_range;
use ast_graph::ResolutionMethod;
use language_support::Language;
use language_support::TSLanguage;
use language_support::TSLanguageConfig;

use crate::ast::ast_graph::{EdgeKind, ScopeGraph};
pub struct CodeFileAST<'a> {
    /// The original source that was used to generate this file.
    src: &'a [u8],

    /// The syntax tree of this file.
    tree: Tree,

    /// The supplied language for this file.
    language: &'static TSLanguageConfig,
}

#[derive(Debug)]
pub enum CodeFileASTError {
    UnsupportedLanguage,
    ParseTimeout,
    LanguageMismatch,
    QueryError(tree_sitter::QueryError),
    FileTooLarge,
}

impl<'a> CodeFileAST<'a> {
    /// Create a TreeSitterFile out of a sourcefile
    pub fn build_ast(src: &'a [u8], lang_id: &str) -> Result<Self, CodeFileASTError> {
        // no scope-res for files larger than 500kb
        if src.len() > 500 * 10usize.pow(3) {
            return Err(CodeFileASTError::FileTooLarge);
        }

        let language = match TSLanguage::from_id(lang_id) {
            Language::Supported(language) => Ok(language),
            Language::Unsupported => Err(CodeFileASTError::UnsupportedLanguage),
        }?;

        let mut parser = Parser::new();
        parser
            .set_language((language.grammar)())
            .map_err(|_| CodeFileASTError::LanguageMismatch)?;

        // do not permit files that take >1s to parse
        parser.set_timeout_micros(10u64.pow(6));

        let tree = parser
            .parse(src, None)
            .ok_or(CodeFileASTError::ParseTimeout)?;
        // print the syntax tree as s-expressions
        // println!("{:#?}", tree.root_node().to_sexp());
        Ok(Self {
            src,
            tree,
            language,
        })
    }
    /// Produce a lexical scope-graph for this TreeSitterFile.
    pub fn scope_graph(self) -> Result<ScopeGraph, CodeFileASTError> {
        let query = self
            .language
            .scope_query
            .query(self.language.grammar)
            .map_err(CodeFileASTError::QueryError)?;
        let root_node = self.tree.root_node();

        Ok(ResolutionMethod::Generic.build_scope(query, root_node, self.src, self.language))
    }
}
