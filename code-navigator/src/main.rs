pub mod tester;

use std::path::PathBuf;

use crate::tester::Tester;
use anyhow::Result;
use tree_sitter_stack_graphs::loader::{LanguageConfiguration, LoadError, Loader};
use tree_sitter_stack_graphs::CancellationFlag;
use tree_sitter_stack_graphs::NoCancellation;

// This documentation test is not meant to test Python's actual stack graph
// construction rules.  An empty TSG file is perfectly valid (it just won't produce any stack
// graph content).  This minimizes the amount of work that we do when running `cargo test`.
static STACK_GRAPH_RULES: &str = "";

// fn main() -> Result<(), Box<dyn std::error::Error>> {
//     let python_source = r#"
//     import sys
//     print(sys.path)
//     "#;
//     let grammar = tree_sitter_python::language();
//     let tsg_source = STACK_GRAPH_RULES;
//     let mut language = StackGraphLanguage::from_str(grammar, tsg_source)?;
//     let mut stack_graph = StackGraph::new();
//     let file_handle = stack_graph.get_or_create_file("test.py");
//     let globals = Variables::new();
//     language.build_stack_graph_into(
//         &mut stack_graph,
//         file_handle,
//         python_source,
//         &globals,
//         &NoCancellation,
//     )?;
//     Ok(())
// }

/// The stack graphs tsg source for this language.
pub const STACK_GRAPHS_TSG_PATH: &str = "./languages/python/stack-graphs.tsg";
/// The stack graphs tsg source for this language.
pub const STACK_GRAPHS_TSG_SOURCE: &str = include_str!("./languages/python/stack-graphs.tsg");

/// The stack graphs builtins configuration for this language.
pub const STACK_GRAPHS_BUILTINS_CONFIG: &str = include_str!("./languages/python/builtins.cfg");
/// The stack graphs builtins path for this language
pub const STACK_GRAPHS_BUILTINS_PATH: &str = "./languages/python/builtins.py";
/// The stack graphs builtins source for this language.
pub const STACK_GRAPHS_BUILTINS_SOURCE: &str = include_str!("./languages/python/builtins.py");

/// The test python files for this language.
pub const TESTS_PATH: &str = "./src/languages/python/tests";

/// The name of the file path global variable.
pub const FILE_PATH_VAR: &str = "FILE_PATH";

pub fn language_configuration(
    cancellation_flag: &dyn CancellationFlag,
) -> Result<LanguageConfiguration, LoadError> {
    LanguageConfiguration::from_sources(
        tree_sitter_python::language(),
        Some(String::from("source.py")),
        None,
        vec![String::from("py")],
        STACK_GRAPHS_TSG_PATH.into(),
        STACK_GRAPHS_TSG_SOURCE,
        Some((
            STACK_GRAPHS_BUILTINS_PATH.into(),
            STACK_GRAPHS_BUILTINS_SOURCE,
        )),
        Some(STACK_GRAPHS_BUILTINS_CONFIG),
        cancellation_flag,
    )
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    print!("Hello World!");
    test_python_paths();
    Ok(())
}

fn test_python_paths() -> Result<()> {
    let test_path = PathBuf::from(TESTS_PATH);
    let lc = language_configuration(&NoCancellation)?;
    let mut loader = Loader::from_language_configurations(vec![lc], None).expect("Expected loader");
    Tester::new(vec![test_path]).run(loader);

    Ok(())
}
