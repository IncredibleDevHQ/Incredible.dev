use ast::symbol::SymbolMetaData;
// Import necessary modules from Rust's standard library
use bincode::serialize;
use config::get_qdrant_url;
use futures::{executor::block_on, future::join_all};
use qdrant_client::qdrant;
use serde::Serialize;
use std::collections::HashMap;
use std::error::Error;
use std::fmt;
use std::path::PathBuf;
use tokio;
use clap::Parser;
// Import the index_filter module
mod index_filter;
use index_filter::index_filter;
mod hash;
use hash::compute_hashes;
mod util;
use std::collections::HashSet;
use util::detect_language;
// External crate for working with Git repositories
use std::env;
mod config;
mod generate_index_schema;
mod index_processor;

extern crate git2;
mod ast;
use crate::ast::symbol::{SymbolKey, SymbolLocations, SymbolValue};
use crate::ast::CodeFileAST;
use crate::semantic_index::{SemanticError, SemanticIndex};
// Importing necessary types from the git2 crate
use git2::{ObjectType, Repository as GitRepository};
use qdrant_client::prelude::{QdrantClient, QdrantClientConfig};
use qdrant_client::qdrant::CollectionOperationResponse;
use qdrant_client::qdrant::{
    vectors_config, CreateCollection, Distance, FieldType, VectorParams, VectorsConfig,
};
use tracing::debug;

mod semantic_index;
// Enum to represent the file type
#[derive(Clone)]
enum FileType {
    File,
    Dir,
    Other,
}

pub const AVG_LINE_LEN: u64 = 30;
pub const MAX_LINE_COUNT: u64 = 20000;
pub const MAX_FILE_LEN: u64 = AVG_LINE_LEN * MAX_LINE_COUNT;
const COLLECTION_NAME: &str = "documents";
const COLLECTION_NAME_SYMBOLS: &str = "documents_symbol";
const EMBEDDING_DIM: usize = 384;

// data structure to represent a repository  file or directory or other.
#[derive(Clone)]
pub enum RepoEntry {
    Dir(CodeDir),
    File(CodeFile),
    Other,
}

// Fetching the path from the RepoEntry.
impl RepoEntry {
    pub fn path(&self) -> &str {
        match self {
            RepoEntry::Dir(dir) => &dir.path,
            RepoEntry::File(file) => &file.path,
            RepoEntry::Other => "",
        }
    }
}

// Directory only contains a path
#[derive(Debug, Clone, Serialize)]
pub struct CodeDir {
    pub path: String,
}

// File contains a path and a buffer
// buffer has the contents of the file
#[derive(Debug, Clone, Serialize)]
pub struct CodeFile {
    pub path: String,
    pub buffer: String,
    semantic_hash: String,
    tantivy_hash: String,
    pub language: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct FileFields {
    repo_name: String,
    repo_disk_path: String,
    repo_ref: String,
    relative_path: String,
    last_commit: String,
    lang: String,
    is_directory: bool,
    avg_line_length: f64,
    line_end_indices: Vec<u8>,
    content: String,
    symbol_locations: Vec<u8>,
    unique_hash: String,
    symbols: String,
}
// Implement the Display trait for FileType.
// This allows us to print out the file type in a human-readable format.
impl fmt::Display for FileType {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        match self {
            FileType::File => write!(f, "File"),
            FileType::Dir => write!(f, "Directory"),
            FileType::Other => write!(f, "Other"),
        }
    }
}

// Implement the Debug trait for FileType.
// This allows us to print detailed information about the file type, useful in debugging.
impl fmt::Debug for FileType {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        match self {
            FileType::File => write!(f, "File"),
            FileType::Dir => write!(f, "Directory"),
            FileType::Other => write!(f, "Other"),
        }
    }
}

// Define a type alias 'Result<T>' for a Result with a dynamic Error type
type Result<T> = std::result::Result<T, Box<dyn Error>>;

// Define some structures to represent various components of a repository.
struct RepoMetadata;
struct IndexWriter;

// Repository struct represents a repository with a disk path.
pub struct Repository {
    disk_path: PathBuf,
    repo_name: String,
    git_repo: GitRepository,
    file_entries: HashMap<String, EntryData>, // The file_entries HashMap
    repo_entries: Vec<RepoEntry>,             // The repo_entries Vec
    qdrant_client_code_chunk: Option<QdrantClient>,
    qdrant_client_symbol: Option<QdrantClient>,
    semantic_payloads: Vec<SemanticPayload>,
    symbol_meta_payload: HashMap<SymbolKey, Vec<SymbolValue>>,
}

pub struct SemanticPayload {
    path: String,
    buffer: String,
    semantic_hash: String,
    language: String,
}

#[derive(Clone)]
struct EntryData {
    file_type: FileType,
    git_id: git2::Oid, // Assuming GitID is a type you have defined elsewhere
}

// Define an enum to represent possible errors that can occur with a repository.
pub enum RepositoryError {
    InvalidPath,
    GitError(git2::Error), // Include git2::Error as a variant
}

// Implement the Display trait for RepositoryError.
// This allows us to print out the error message associated with the error.
impl fmt::Display for RepositoryError {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        match self {
            RepositoryError::InvalidPath => write!(f, "Invalid repository disk path."),
            RepositoryError::GitError(err) => write!(f, "Git error: {}", err), // Print underlying git2::Error
        }
    }
}

// Implement the Debug trait for RepositoryError.
// This allows us to print detailed information about the error, useful in debugging.
impl fmt::Debug for RepositoryError {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        match self {
            RepositoryError::InvalidPath => write!(f, "Invalid repository disk path."),
            RepositoryError::GitError(err) => write!(f, "Git error: {}", err), // Print underlying git2::Error
        }
    }
}

/*
The source method of the Error trait is used to expose the underlying cause of an error.
In other words, it's used when one error is directly caused by another, and you want to provide access to that underlying "source" error.

In the given code, the RepositoryError::GitError variant includes an underlying git2::Error.
This is a specific error that comes from the git2 crate, and it makes sense to expose it as the source of the RepositoryError::GitError.

On the other hand, the RepositoryError::InvalidPath variant doesn't encapsulate another error.
It's a standalone error that represents an invalid path. Since there is no underlying error to expose, the implementation of the source method returns None for this variant.

This pattern is common when implementing the Error trait. You expose underlying errors where they exist and return None for cases where there is no underlying error. It allows consumers of your error type to potentially explore a chain of errors, drilling down into the root cause, if there is such a chain to explore.
In the case of RepositoryError::InvalidPath, there is no such chain, so None is the appropriate value to return.

*/
impl Error for RepositoryError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            RepositoryError::GitError(err) => Some(err), // Return underlying git2::Error
            _ => None,
        }
    }
}

/*
1. **`impl From<git2::Error> for RepositoryError`**: This line starts the implementation of the `From` trait for converting from `git2::Error` into `RepositoryError`.
 The `From` trait is a standard Rust trait used to define conversions between types.

2. **`fn from(err: git2::Error) -> Self`**: This line defines the function signature for the required `from` method of the `From` trait.
   - `err: git2::Error` is the input parameter, the error type from the `git2` crate that we want to convert.
   - `-> Self` means that the return type of the function is the type for which `From` is implemented, in this case, `RepositoryError`.

3. **`RepositoryError::GitError(err)`**: Inside the function body, we are constructing a `RepositoryError::GitError` variant, passing in the original `git2::Error` (`err`).
 This is assuming that `RepositoryError` is an enum with a variant `GitError` that takes a `git2::Error` as a parameter.

The purpose of this code is to provide a way to easily convert a `git2::Error` into a `RepositoryError`. Once this implementation is in place, you can use the `from` function directly, or rely on the `Into` trait, which is automatically available wherever `From` is implemented.

This kind of pattern is common when working with different libraries that have their own error types, and you want to unify them into a single application-specific error type.
By doing this, you can handle errors from different sources in a consistent way, making your code more robust and easier to maintain.
*/
impl From<git2::Error> for RepositoryError {
    fn from(err: git2::Error) -> Self {
        RepositoryError::GitError(err)
    }
}

impl Repository {
    pub fn collection_config(collection_name: String) -> CreateCollection {
        CreateCollection {
            collection_name: collection_name,
            vectors_config: Some(VectorsConfig {
                config: Some(vectors_config::Config::Params(VectorParams {
                    size: EMBEDDING_DIM as u64,
                    distance: Distance::Cosine.into(),
                    ..Default::default()
                })),
            }),
            ..Default::default()
        }
    }

    // Note: Changed from &self to no self argument.
    async fn init_qdrant_client(
        qdrant_url: &str,
        collection_name: &str,
        indexes: Vec<String>,
    ) -> Result<QdrantClient> {
        let qdrant = QdrantClient::new(Some(QdrantClientConfig::from_url(qdrant_url))).unwrap();

        // check if the collection exists, create it if it doesn't.
        match qdrant.has_collection(collection_name).await {
            Ok(false) => {
                let CollectionOperationResponse { result, time } = qdrant
                    .create_collection(&Repository::collection_config(collection_name.to_string()))
                    .await
                    .unwrap();

                debug!(
                    time,
                    created = result,
                    name = COLLECTION_NAME,
                    "created qdrant collection"
                );

                assert!(result);
            }
            Ok(true) => {}
            Err(e) => {
                // print the error  message from Err.
                println!("Error: {:?}", e);
                // return early with error

                return Err(Box::new(SemanticError::QdrantInitializationError));
            }
        }

        //iterate through the indexes and create field indexes
        for index in indexes.iter() {
            let result = qdrant
                .create_field_index(collection_name, index, FieldType::Text, None, None)
                .await?;
        }
        /*
                // At this point, all futures have succeeded and their results are in the `results` vector.
                qdrant
                    .create_field_index(COLLECTION_NAME, "repo_name", FieldType::Text, None, None)
                    .await?;
                qdrant
                    .create_field_index(COLLECTION_NAME, "content_hash", FieldType::Text, None, None)
                    .await?;
                qdrant
                    .create_field_index(
                        COLLECTION_NAME,
                        "relative_path",
                        FieldType::Text,
                        None,
                        None,
                    )
                    .await?;
        */
        Ok(qdrant)
    }

    // Note: Changed from &mut self to no self argument, and modified the return type.
    pub async fn new(disk_path: PathBuf, repo_name: String) -> Result<Self> {
        let indexes_chunk = vec![
            "repo_name".to_string(),
            "content_hash".to_string(),
            "relative_path".to_string(),
        ];

        let indexes_symbols = vec!["repo_name".to_string(), "symbol".to_string()];
        let git_repo = GitRepository::open(&disk_path)?;
        let qdrant_client_chunks = Some(
            Repository::init_qdrant_client(&get_qdrant_url(), COLLECTION_NAME, indexes_chunk)
                .await?,
        );
        let qdrant_client_symbols = Some(
            Repository::init_qdrant_client(
                &get_qdrant_url(),
                COLLECTION_NAME_SYMBOLS,
                indexes_symbols,
            )
            .await?,
        );

        Ok(Self {
            disk_path,
            repo_name,
            git_repo,
            file_entries: HashMap::new(),
            repo_entries: Vec::new(),
            qdrant_client_code_chunk: qdrant_client_chunks,
            qdrant_client_symbol: qdrant_client_symbols,
            semantic_payloads: Vec::new(),
            symbol_meta_payload: HashMap::new(),
        })
    }

    pub async fn traverse(&mut self, repo_path: &str, repo_name: &str, branch: &str) -> Result<()> {
        // Find the reference to the main branch

        // Create a Vec to store all the RepoEntry::File entries
        let mut all_entries: Vec<FileFields> = Vec::new();

        let head_ref = self.git_repo.find_reference(branch)?;
        let head_commit = self.git_repo.find_commit(head_ref.target().unwrap())?;
        let tree = head_commit.tree()?;
        // let rt = tokio::runtime::Builder::new_current_thread()
        //     .enable_all()
        //     .build()
        //     .unwrap();

        // Walk through the tree, visiting each entry in a pre-order traversal
        let mut counter = 0;
        // Walk through the given Git tree, using pre-order traversal.
        tree.walk(git2::TreeWalkMode::PreOrder, |root, entry| {
            // If the entry has a name, get its path.
            if let Some(name) = entry.name() {
                let path = format!("{}{}", root, name);

                // If the file at the given path should not be indexed, skip it.
                if !index_filter(&path) {
                    println!("Skipping {}", path);
                    return git2::TreeWalkResult::Ok;
                }

                // Determine the type of file (directory, regular file, or other).
                let file_type = match entry.kind().unwrap() {
                    ObjectType::Tree => FileType::Dir,
                    ObjectType::Blob => FileType::File,
                    _ => FileType::Other,
                };

                // Retrieve the Git ID for the entry.
                let git_id = entry.id();
                println!("{}: {:?} ({})", path, file_type, git_id);
                let entry_data = EntryData { file_type, git_id };

                // Store the file entry information into the `file_entries` HashMap.
                self.file_entries.insert(path.clone(), entry_data);

                let path = format!("{}{}", root, name);
                println!("Path path path: {}", path);

                // Match the object type of the entry.
                let object_type = entry.kind().unwrap();
                match object_type {
                    // If it's a directory, push it to the `repo_entries` Vec.
                    ObjectType::Tree => {
                        self.repo_entries.push(RepoEntry::Dir(CodeDir { path }));
                    }
                    // If it's a regular file (blob in Git terms), process the file.
                    ObjectType::Blob => {
                        let blob = self.git_repo.find_blob(git_id).unwrap();
                        let path_buf = PathBuf::from(&path);
                        let content_buffer = blob.content();

                        // Skip the file if its size exceeds the maximum allowed file length.
                        if content_buffer.len() > MAX_FILE_LEN as usize {
                            println!("Skipping file due to size: {}", path);
                            return git2::TreeWalkResult::Ok;
                        }

                        // Convert the content of the blob into a UTF-8 string.
                        let mut buffer = std::str::from_utf8(content_buffer)
                            .unwrap_or("")
                            .to_string();

                        // Compute the relative path for the file.
                        let relative_path = PathBuf::from(&path)
                            .strip_prefix(&self.disk_path)
                            .map(ToOwned::to_owned)
                            .unwrap_or(PathBuf::from(&path));

                        // Compute the semantic and tantivy hashes for the file. NOTE: "main" is hardcoded.
                        let (semantic_hash, tantivy_hash) =
                            compute_hashes(relative_path, &buffer, "main");

                        // Detect the programming language of the file.
                        let language = util::detect_language(&path_buf, blob.content())
                            .map(|s| s.to_string())
                            .unwrap_or("Unknown".to_string());

                        // If the language is unsupported, skip the file.
                        if language == "Unknown" {
                            print!("Unsupported language: {}", language);
                            return git2::TreeWalkResult::Ok;
                        }

                        // Build a syntax-aware representation of the file.
                        let symbol_locations = {
                            let scope_graph = CodeFileAST::build_ast(blob.content(), &language)
                                .and_then(CodeFileAST::scope_graph);

                            // Return the graph if it exists or return an empty representation.
                            match scope_graph {
                                Ok(graph) => SymbolLocations::TreeSitter(graph),
                                Err(err) => SymbolLocations::Empty,
                            }
                        };

                        // Extract symbols from the syntax-aware representation.
                        let symbols = symbol_locations
                            .list()
                            .iter()
                            .map(|sym| buffer[sym.range.start.byte..sym.range.end.byte].to_owned())
                            .collect::<HashSet<_>>()
                            .into_iter()
                            .collect::<Vec<_>>()
                            .join("\n");

                        // Collect and aggregate metadata for each symbol in the file.
                        // This is to utilize the symbols during code search and perform ranking.
                        self.symbol_meta_payload = symbol_locations
                            .list_metadata(blob.content(), repo_name, &language, &path)
                            .into_iter()
                            .fold(self.symbol_meta_payload.clone(), |mut meta_map, meta| {
                                let meta_key = SymbolKey {
                                    symbol: meta.symbol_type.clone(),
                                    repo_name: meta.repo_name.clone(),
                                };

                                let meta_value = SymbolValue {
                                    symbol_type: meta.symbol.clone(),
                                    language_id: meta.language_id.clone(),
                                    relative_path: meta.relative_path.clone(),
                                    start_byte: meta.range.start.byte.clone(),
                                    end_byte: meta.range.end.byte.clone(),
                                    is_global: meta.is_global.clone(),
                                    node_kind: meta.node_kind.clone(),
                                };

                                meta_map
                                    .entry(meta_key)
                                    .or_insert_with(Vec::new)
                                    .push(meta_value);

                                meta_map
                            });

                        println!("Symbol Meta Payload: {:?}", self.symbol_meta_payload);

                        // Ensure the content ends with a newline.
                        if !buffer.ends_with('\n') {
                            buffer += "\n";
                        }

                        // Compute line ending indices for the file.
                        let line_end_indices = buffer
                            .match_indices('\n')
                            .flat_map(|(i, _)| u32::to_le_bytes(i as u32))
                            .collect::<Vec<_>>();

                        // Skip files that have too many lines.
                        if line_end_indices.len() > MAX_LINE_COUNT as usize {
                            return git2::TreeWalkResult::Ok;
                        }

                        let lines_avg = buffer.len() as f64 / buffer.lines().count() as f64;

                        // Convert the path from PathBuf to &str and process further.
                        if let Some(path_str) = path_buf.as_path().to_str() {
                            println!("Path as &str: {}", path_str);

                            // Create a struct to store various semantic data.
                            self.semantic_payloads.push(SemanticPayload {
                                path: path_str.to_string(),
                                buffer: buffer.clone(),
                                semantic_hash: semantic_hash.clone(),
                                language: language.clone(),
                            });
                        } else {
                            println!("Path is not valid UTF-8");
                            return git2::TreeWalkResult::Ok;
                        }

                        // Create a struct to store various fields about the file.
                        let file_fields = FileFields {
                            repo_name: repo_name.to_string(),
                            // use the disk path of the repo.
                            repo_disk_path: repo_path.to_string(),
                            repo_ref: String::new(),
                            lang: language.clone(),
                            relative_path: path.clone(),
                            last_commit: String::new(),
                            is_directory: false,
                            avg_line_length: lines_avg,
                            line_end_indices: line_end_indices.clone(),
                            content: buffer.clone(),
                            symbol_locations: bincode::serialize(&symbol_locations).unwrap(),
                            unique_hash: tantivy_hash.clone(),
                            symbols: symbols.clone(),
                        };

                        // Store the file data in the all_entries Vec.
                        all_entries.push(file_fields.clone());

                        // Add the processed file to the repo_entries Vec.
                        self.repo_entries.push(RepoEntry::File(CodeFile {
                            path,
                            buffer,
                            semantic_hash,
                            tantivy_hash,
                            language,
                        }));
                    }
                    // If it's neither a directory nor a regular file, store it as "Other".
                    _ => self.repo_entries.push(RepoEntry::Other),
                }
            }
            // Continue walking through the tree.
            git2::TreeWalkResult::Ok
        })?;

        // iterate through self.semanticPayloads and call the tokenize_and_commit function
        for payload in &self.semantic_payloads {
            let mut index = SemanticIndex::new(&counter)?;
            let result = index
                .tokenize_and_commit(
                    &payload.buffer,
                    &self.repo_name,
                    &payload.path,
                    &payload.semantic_hash,
                    &payload.language,
                    &self.qdrant_client_code_chunk,
                )
                .await;
            // print saying committing finished.
            println!("Committing finished");
            // increment the counter
            counter += 1;

            println!("Counter value: {}", counter);
        }

        let mut index = SemanticIndex::new(&counter)?;
        // send self.symbolMetaPayload to commit_symbol_metadata function to commit the metadata.
        let result = index
            .commit_symbol_metadata(&self.symbol_meta_payload, &self.qdrant_client_symbol)
            .await;

        if let Err(e) = result {
            println!("Error: {:?}", e);
        }

        // index to quickwit
        index_processor::process_entries(all_entries, repo_name).await;

        Ok(())
    }
}

// Define a structure to represent an Indexer.
struct Indexer;

impl Indexer {
    async fn index_repository(
        &self,
        disk_path: PathBuf,
        _metadata: &RepoMetadata,
        _writer: &IndexWriter,
        repo_name: String,
        branch: &str,
    ) -> Result<()> {
        // Create a new Repository instance using the `new` method.
        let repo_path_string = disk_path.to_str().unwrap().to_string();
        let mut repo = Repository::new(disk_path, repo_name.clone()).await?;
        // Call the traverse method to list the files in the repository.
        repo.traverse(&repo_path_string, &repo_name.clone(), branch)
            .await?;
        // Print the disk path of the repository.
        print!("Indexing repository at path: {:?}", repo.disk_path);
        println!("Indexing repository at path: {:?}", repo.disk_path);

        Ok(())
    }
}


/// Application to process repository data
#[derive(Parser, Debug)]
#[command(version = "0.1", about = "Index repository data", long_about = None)]
struct Args {
    /// Name to the repository folder inside ./repo/ directory
    #[arg(long, help = "Sets the repository folder to process")]
    repo_folder: String,

    /// Identifier for the repository, used to later perform search and agent operations on the repo.
    #[arg(long, help = "Sets the repository ID")]
    repo_id: String,

    #[arg(long, help = "Sets the branch to be indexed")]
    branch: Option<String>,
}

#[tokio::main]

async fn main() -> Result<()> {
    env_logger::init();

    let args = Args::parse();

    log::info!("Processing repository folder: {}", args.repo_folder);
    log::info!("Using repository ID: {}", args.repo_id);

    // defaults to main branch if branch is not set.
    let branch = args.branch.unwrap_or_else(|| "refs/heads/main".to_string());

    // Path to the repository
    let repo_base_path = env::current_dir()?.join("repo").join(&args.repo_folder);
    log::info!("Full repository path: {:?}", repo_base_path);

    // Instantiate an Indexer.
    let indexer = Indexer;

    // Instantiate some additional components of a repository.
    let metadata = RepoMetadata;
    let writer = IndexWriter;

    // Use the indexer to index the repository, passing the disk path.
    indexer
        .index_repository(repo_base_path, &metadata, &writer, args.repo_id, &branch)
        .await
}
