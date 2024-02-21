use std::path::PathBuf;

use tree_sitter_stack_graphs::{
    cli::index::IndexArgs,
    loader::{LanguageConfiguration, Loader},
    NoCancellation,
};
use tree_sitter_stack_graphs_python::language_configuration;

fn get_language_configurations(language: &str) -> Vec<LanguageConfiguration> {
    match language {
        "Python" => vec![language_configuration(&NoCancellation)],
        _ => vec![],
    }
}

pub fn index_files(files: Vec<PathBuf>, language: &str) -> Result<(), anyhow::Error> {
    let language_configurations = get_language_configurations(language);

    let index_args = IndexArgs {
        source_paths: files,
        continue_from: None,
        verbose: true,
        hide_error_details: false,
        max_file_time: None,
        wait_at_start: false,
        stats: true,
        force: true,
    };

    // Specify the default database path (adjust as necessary)
    let directory = match std::env::current_dir() {
        Ok(path) => path,
        Err(e) => {
            println!("Error getting the current directory: {}", e);
            PathBuf::new()
        }
    };
    let default_db_path = directory
        .join(format!("{}.sqlite", env!("CARGO_PKG_NAME")))
        .to_path_buf();

    let loader = Loader::from_language_configurations(language_configurations, None)
        .expect("Expected loader");

    log::info!(
        "Starting graph infexing inside {} \n",
        default_db_path.display()
    );

    // Now, run the indexing process
    index_args.run(&default_db_path, loader)
}
