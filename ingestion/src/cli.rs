use std::path::PathBuf;

use clap::{App, Arg};
use ingestion::{Config, Indexer};
use log::info;

pub async fn execute() {
    let matches = App::new("Ingestion Service")
        .version("0.1")
        .author("superspace <team@superspace.so>")
        .about("Handles custom repo configuration")
        .arg(
            Arg::new("repo_name")
                .help("The name of the repository")
                .required(true)
                .index(1),
        )
        .arg(
            Arg::new("repo_path")
                .help("The path to the repository")
                .required(true)
                .index(2),
        )
        .arg(
            Arg::new("qdrant_url")
                .long("qdrant-url")
                .help("The URL of the Qdrant service")
                .takes_value(true)
                .env("QDRANT_URL")
                .default_value("http://localhost:6334"),
        )
        .arg(
            Arg::new("quickwit_url")
                .long("quickwit-url")
                .help("The URL of the Quickwit service")
                .takes_value(true)
                .env("QUICKWIT_URL")
                .default_value("http://localhost:7280"),
        )
        .arg(
            Arg::new("qdrant_api_key")
                .long("qdrant-api-key")
                .help("The API key for Qdrant")
                .takes_value(true)
                .env("QDRANT_API_KEY")
                .default_value("default_api_key"),
        )
        .arg(
            Arg::new("branch")
                .long("branch")
                .help("The branch to index")
                .takes_value(true)
                .default_value("main"),
        )
        .arg(
            Arg::new("version")
                .long("version")
                .help("Take the current ingestion version")
                .takes_value(true)
                .default_value("v2"),
        )
        .get_matches();

    let repo_name = matches.value_of("repo_name").unwrap();
    let disk_path_str = matches.value_of("repo_path").unwrap();
    let qdrant_url = matches.value_of("qdrant_url").unwrap();
    let quickwit_url = matches.value_of("quickwit_url").unwrap();
    let qdrant_api_key = matches.value_of("qdrant_api_key").unwrap();
    let branch = matches.value_of("branch").unwrap();
    let version = matches.value_of("version").unwrap();

    info!("Repo name: {}", repo_name);
    info!("Repo path: {}", disk_path_str);
    info!("Qdrant URL: {}", qdrant_url);
    info!("Quickwit URL: {}", quickwit_url);
    info!("Qdrant API key: {}", qdrant_api_key);
    info!("Branch: {}", branch);
    info!("Version: {}", version);

    // Instantiate an Indexer.
    let indexer = Indexer;

    // Create a disk path pointing to a valid Git repository.
    let disk_path = PathBuf::from(disk_path_str);

    let config = Config::new(
        repo_name.to_string(),
        disk_path_str.to_string(),
        qdrant_url.to_string(),
        quickwit_url.to_string(),
        qdrant_api_key.to_string(),
        branch.to_string(),
        version.to_string(),
    );

    // Use the indexer to index the repository, passing the disk path.
    let _ = indexer
        .index_repository(disk_path, repo_name.to_string(), config, branch, version)
        .await;
}
