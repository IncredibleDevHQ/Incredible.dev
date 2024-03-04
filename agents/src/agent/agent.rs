use hashbrown::HashMap;
use serde::{Deserialize, Serialize};
use std::hash::Hash;
use std::time::Duration;
use std::sync::Arc;

use crate::agent::graph::symbol;
use crate::agent::llm_gateway::{self, api::FunctionCall};
use crate::{parser, AppState};
use crate::search::payload::{CodeExtractMeta, PathExtractMeta};
use crate::search::semantic::SemanticQuery;
use anyhow::{anyhow, Context, Result};
use futures::stream::{StreamExt, TryStreamExt}; // Ensure these are imported
use tokio::sync::mpsc::Sender;
use tracing::{debug, info, instrument};

use crate::agent::graph::scope_graph::{get_line_number, SymbolLocations};

use crate::config::Config;

// Types of repo
#[derive(Serialize, Deserialize, Hash, PartialEq, Eq, Clone, Debug)]
#[serde(rename_all = "snake_case")]
pub enum Backend {
    Local,
    Github,
}
#[derive(Hash, Eq, PartialEq, Debug, Clone)]
pub struct RepoRef {
    pub backend: Backend,
    pub name: String,
}

#[derive(Default, Debug, Clone)]
pub struct ExtractedContent {
    pub path: String,
    pub content: String,
    pub start_byte: usize,
    pub end_byte: usize,
    pub start_line: usize,
    pub end_line: usize,
}

#[derive(Default, Debug, Clone)]
pub struct ContentDocument {
    pub repo_name: String,
    pub repo_ref: String,
    pub relative_path: String,
    pub lang: Option<String>,
    pub line_end_indices: Vec<u8>,
    pub content: String,
    pub symbol_locations: Vec<u8>,
    pub symbols: String,
}


#[derive(Debug, Eq, PartialEq, Hash, Serialize, Deserialize, Clone)]
pub struct FileDocument {
    pub relative_path: String,
    pub repo_name: String,
    pub repo_ref: String,
    pub lang: Option<String>,
}

use crate::agent::exchange::{Exchange, SearchStep, Update};

use crate::agent::prompts;
use crate::agent::tools::{answer, code, path, proc};
use crate::agent::transform;

use super::graph::scope_graph::ScopeGraph;

/// A collection of modules that each add methods to `Agent`.
///
/// These methods correspond to `Action` handlers, and often have supporting methods and supporting
/// functions, that are local to their own implementation. These modules also have independent
/// tests.

pub const ANSWER_MODEL: &str = "gpt-4-0613";

pub enum AgentError {
    Timeout(Duration),
    Processing(anyhow::Error),
}

pub struct Agent {
    pub app_state: Arc<AppState>,
    pub exchanges: Vec<Exchange>,

    pub llm_gateway: llm_gateway::Client,

    pub query_id: uuid::Uuid,

    /// Indicate whether the request was answered.
    ///
    /// This is used in the `Drop` handler, in order to track cancelled answer queries.
    pub complete: bool,
}

/// We use a `Drop` implementation to track agent query cancellation.
///
/// Query control flow can be complex, as there are several points where an error may be returned
/// via `?`. Rather than dealing with this in a complex way, we can simply use `Drop` destructors
/// to send cancellation messages to our analytics provider.
///
/// By default, dropping an agent struct will send a cancellation message. However, calling
/// `.complete()` will "diffuse" tracking, and disable the cancellation message from sending on drop.
impl Drop for Agent {
    fn drop(&mut self) {
        if !self.complete {
            println!("Dropping agent");
        }
    }
}

// gien the start and end byte, readjust them to cover the entire start line and the entire end line.
pub fn adjust_byte_positions(
    new_start: usize,
    temp_new_end: usize,
    line_end_indices: &Vec<usize>,
) -> (usize, usize) {
    let ending_line = get_line_number(temp_new_end, &line_end_indices);
    let starting_line = get_line_number(new_start, &line_end_indices);

    // If possible, use the ending of the previous line to determine the start of the current line.
    let mut previous_line = starting_line;
    if previous_line > 0 {
        previous_line -= 1;
    }

    // Adjust the start and end byte positions based on line numbers for a clearer context.
    let adjusted_start = line_end_indices
        .get(previous_line)
        .map(|l| *l as usize)
        .unwrap_or(new_start)
        + 1;
    let adjusted_end = line_end_indices
        .get(ending_line)
        .map(|l: &usize| *l as usize)
        .unwrap_or(temp_new_end);

    (adjusted_start, adjusted_end)
}

impl Agent {
    /// Complete this agent, preventing an analytics message from sending on drop.
    pub fn complete(mut self) {
        // Checked in `Drop::drop`
        self.complete = true;
    }

    /// Update the last exchange
    #[instrument(skip(self), level = "debug")]
    pub fn update(&mut self, update: Update) -> Result<()> {
        self.last_exchange_mut().apply_update(update);
        //println!("update {:?}", update);
        Ok(())
    }

    pub fn last_exchange(&self) -> &Exchange {
        self.exchanges.last().expect("exchange list was empty")
    }

    fn last_exchange_mut(&mut self) -> &mut Exchange {
        self.exchanges.last_mut().expect("exchange list was empty")
    }

    pub fn paths(&self) -> impl Iterator<Item = &str> {
        self.exchanges
            .iter()
            .flat_map(|e| e.paths.iter())
            .map(String::as_str)
    }

    pub fn get_path_alias(&mut self, path: &str) -> usize {
        // This has to be stored a variable due to a Rust NLL bug:
        // https://github.com/rust-lang/rust/issues/51826
        let pos = self.paths().position(|p| p == path);
        if let Some(i) = pos {
            i
        } else {
            let i = self.paths().count();
            self.last_exchange_mut().paths.push(path.to_owned());
            i
        }
    }

    #[instrument(skip(self))]
    pub async fn step(&mut self, action: Action) -> Result<Option<Action>> {
        println!("\ninside step {:?}\n", action);

        match &action {
            Action::Query(s) => s.clone(),

            Action::Answer { paths } => {
                self.answer(paths).await.context("answer action failed")?;
                return Ok(None);
            }

            Action::Path { query } => self.path_search(query).await?,
            Action::Code { query } => self.code_search(query).await?,
            Action::Proc { query, paths } => self.process_files(query, paths).await?,
        };

        let functions = serde_json::from_value::<Vec<llm_gateway::api::Function>>(
            prompts::functions(self.paths().next().is_some()), // Only add proc if there are paths in context
        )
        .unwrap();

        let mut history = vec![llm_gateway::api::Message::system(&prompts::system(
            self.paths(),
        ))];
        history.extend(self.history()?);

        println!("full history:\n {:?}", history);

        let trimmed_history = trim_history(history.clone())?;

        println!("trimmed history:\n {:?}", trimmed_history);
        let chat_completion = self
            .llm_gateway
            .chat(&trim_history(history.clone())?, Some(&functions))
            .await?;

        let choice = chat_completion.choices[0].clone();
        let functions_to_call = choice.message.function_call.unwrap().to_owned();
        // print the next action picked.
        println!("{:?} next action", functions_to_call);

        // println!("full_history:\n {:?}\n", &history);
        //println!("trimmed_history:\n {:?}\n", &trimmed_history);
        // println!("last_message:\n {:?} \n", history.last());
        // println!("functions:\n {:?} \n", &functions);
        // println!("raw_response:\n {:?} \n", &chat_completion);

        let action = Action::deserialize_gpt(&functions_to_call)
            .context("failed to deserialize LLM output")?;

        Ok(Some(action))
    }

    /// The full history of messages, including intermediate function calls
    fn history(&self) -> Result<Vec<llm_gateway::api::Message>> {
        const ANSWER_MAX_HISTORY_SIZE: usize = 3;
        const FUNCTION_CALL_INSTRUCTION: &str = "Call a function. Do not answer";

        let history = self
            .exchanges
            .iter()
            .rev()
            .take(ANSWER_MAX_HISTORY_SIZE)
            .rev()
            .try_fold(Vec::new(), |mut acc, e| -> Result<_> {
                let query = e
                    .query()
                    .map(|q| llm_gateway::api::Message::user(&q))
                    .ok_or_else(|| anyhow!("query does not have target"))?;

                let steps = e.search_steps.iter().flat_map(|s| {
                    let (name, arguments) = match s {
                        SearchStep::Path { query, .. } => (
                            "path".to_owned(),
                            format!("{{\n \"query\": \"{query}\"\n}}"),
                        ),
                        SearchStep::Code { query, .. } => (
                            "code".to_owned(),
                            format!("{{\n \"query\": \"{query}\"\n}}"),
                        ),
                        SearchStep::Proc { query, paths, .. } => (
                            "proc".to_owned(),
                            format!(
                                "{{\n \"paths\": [{}],\n \"query\": \"{query}\"\n}}",
                                paths
                                    .iter()
                                    .map(|path| self
                                        .paths()
                                        .position(|p| p == path)
                                        .unwrap()
                                        .to_string())
                                    .collect::<Vec<_>>()
                                    .join(", ")
                            ),
                        ),
                    };

                    vec![
                        llm_gateway::api::Message::function_call(&FunctionCall {
                            name: Some(name.clone()),
                            arguments,
                        }),
                        llm_gateway::api::Message::function_return(&name, &s.get_response()),
                        llm_gateway::api::Message::user(FUNCTION_CALL_INSTRUCTION),
                    ]
                });

                let answer = match e.answer() {
                    // NB: We intentionally discard the summary as it is redundant.
                    Some((answer, _conclusion)) => {
                        let encoded = transform::encode_summarized(answer, None, "gpt-3.5-turbo")?;
                        Some(llm_gateway::api::Message::function_return("none", &encoded))
                    }

                    None => None,
                };

                acc.extend(
                    std::iter::once(query)
                        .chain(vec![llm_gateway::api::Message::user(
                            FUNCTION_CALL_INSTRUCTION,
                        )])
                        .chain(steps)
                        .chain(answer.into_iter()),
                );
                Ok(acc)
            })?;
        Ok(history)
    }

    // pub async fn get_scope_graphs_for_paths(
    //     &self,
    //     paths: Vec<String>,
    //     code_extract_meta: Vec<PathEx>,
    // ) -> Result<HashMap<String, SymbolLocations>> {
    //     let mut scope_graphs = HashMap::new();

    //     for path in paths {
    //         let symbol_locations: SymbolLocations =
    //             self.get_scope_graph_from_path(&path).await.unwrap();

    //         let sg = symbol_locations
    //             .scope_graph()
    //             .ok_or_else(|| anyhow!("path not supported for /token-value"))?;

    //         let node_idx = sg
    //             .node_by_range(payload.start, payload.end)
    //             .ok_or_else(|| anyhow!("token not supported for /token-value"))?;

    //         let range = sg.graph[sg.value_of_definition(node_idx).unwrap_or(node_idx)].range();

    //         // extend the range to cover the entire start line and the entire end line
    //         let new_start = range.start.byte - range.start.column;
    //         let new_end = source_document
    //             .line_end_indices
    //             .get(range.end.line)
    //             .map(|l| *l as usize)
    //             .unwrap_or(range.end.byte);
    //         let content = source_document.content[new_start..new_end].to_string();

    //         scope_graphs.insert(path, symbol_locations);
    //     }

    //     scope_graphs
    // }

    // pub async fn get_scope_graph_from_path(
    //     &self,
    //     paths: Vec<String>,
    //     code_extract_meta: Vec<CodeExtractMeta>,
    // ) -> Result<SymbolLocations> {

    //     for path in paths {
    //         let source_document = self
    //             .get_file_content(&path)
    //             .await?
    //             .ok_or_else(|| anyhow!("path not found"))?;

    //         let symbol_locations = source_document.symbol_locations;
    //         // print the symbol locations
    //         //println!("symbol_locations: {:?}", symbol_locations);
    //         // deserialize the symbol_locations into a scope graph using bincode deserializer
    //         let symbol_locations: SymbolLocations =
    //             bincode::deserialize(&symbol_locations).unwrap()?;
    //         // print the scope graph

    //         let sg = source_document
    //             .symbol_locations
    //             .scope_graph()
    //             .ok_or_else(|| anyhow!("path not supported for /token-value"))?;

    //         let node_idx = sg
    //             .node_by_range(payload.start, payload.end)
    //             .ok_or_else(|| Error::internal("token not supported for /token-value"))?;

    //         let range = sg.graph[sg.value_of_definition(node_idx).unwrap_or(node_idx)].range(symbol_location?;

    //         // extend the range to cover the entire start line and the entire end line
    //         let new_start = range.start.byte - range.start.column;
    //         let new_end = source_document
    //             .line_end_indices
    //             .get(range.end.line)
    //             .map(|l| *l as usize)
    //             .unwrap_or(range.end.byte);
    //         let content = source_document.content[new_start..new_end].to_string();
    //     }

    //     let content = self.get_file_content(path).await?;
    //     let content_doc = content.unwrap();
    //     // print symbol locations
    //     let symbol_locations = content_doc.symbol_locations;
    //     // print the symbol locations
    //     //println!("symbol_locations: {:?}", symbol_locations);
    //     // deserialize the symbol_locations into a scope graph using bincode deserializer
    //     let symbol_locations: SymbolLocations = bincode::deserialize(&symbol_locations).unwrap();
    //     // print the scope graph
    //     //println!("scope_graph: {:?}", symbol_locations);
    //     //println!("---------------------success deserializing: {:?}-------------", symbol_locations.scope_graph());
    //     Ok(symbol_locations)
    // }

    // Make sure to import StreamExt

    /// Asynchronously processes given file paths and extracts content based on the provided metadata.
    ///
    /// # Arguments
    /// - `code_extract_meta`: A vector containing metadata about file paths and associated extraction details.
    ///
    /// # Returns
    /// - A result containing a vector of `ExtractedContent` or an error.
    pub async fn process_paths(
        &self,
        path_extract_meta: Vec<PathExtractMeta>,
    ) -> Result<Vec<ExtractedContent>, anyhow::Error> {
        // Initialize an empty vector to store the extracted contents.
        let mut results = Vec::new();

        // Iterate over each provided path and its associated metadata.
        for path_meta in &path_extract_meta {
            let path = &path_meta.path;

            println!("inside process path: {:?}", path);
            // Fetch the content of the file for the current path.
            let source_document = self.get_file_content(path).await?;

            // log the error and continue to the next path if the file content is not found.
            if source_document.is_none() {
                println!("file content not found for path: {:?}", path);
                continue;
            }

            // unwrap the source document
            let source_document = source_document.unwrap();

            // Deserialize the symbol locations embedded in the source document.
            let symbol_locations: SymbolLocations =
                bincode::deserialize::<SymbolLocations>(&source_document.symbol_locations).unwrap();

            // Convert the compacted u8 array of line end indices back to their original u32 format.
            let line_end_indices: Vec<usize> = source_document
                .line_end_indices
                .chunks(4)
                .filter_map(|chunk| {
                    // Convert each 4-byte chunk to a u32.
                    if chunk.len() == 4 {
                        let value =
                            u32::from_le_bytes([chunk[0], chunk[1], chunk[2], chunk[3]]) as usize;
                        Some(value)
                    } else {
                        None
                    }
                })
                .collect();

            // Retrieve the scope graph associated with symbol locations.
            let sg = symbol_locations
                .scope_graph()
                .ok_or_else(|| anyhow!("path not supported for /token-value"))?;

            // For each metadata about code extraction, process and extract the required content.
            let top_three_chunks: Vec<&CodeExtractMeta> =
                path_meta.code_extract_meta.iter().take(3).collect();

            for code_meta in top_three_chunks {
                let mut start_byte: usize = code_meta.start_byte.try_into().unwrap();
                let mut end_byte: usize = code_meta.end_byte.try_into().unwrap();

                let mut new_start = start_byte.clone();
                let mut new_end = end_byte.clone();
                // print the start and end byte
                println!(
                    "-symbol start_byte: {:?}, end_byte: {:?}, path: {}, score: {}",
                    start_byte, end_byte, path, path_meta.score
                );
                // Locate the node in the scope graph that spans the range defined by start and end bytes.
                let node_idx = sg.node_by_range(start_byte, end_byte);

                // If we can't find such a node, skip to the next metadata.
                if node_idx.is_none() {
                    // find start and end bytes for 100 bytes above start and 200 bytes below end
                    // check if the start byte greater than 100
                    // check if the end byte less than the length of the file
                    // if yes, then set the new start and end bytes
                    // print the new start and end bytes
                    println!("start_byte: {:?}, end_byte: {:?}", start_byte, end_byte);
                    if start_byte > 300 {
                        new_start = start_byte - 300;
                    } else {
                        new_start = 0;
                    }

                    if end_byte + 300 < source_document.content.len() {
                        new_end = end_byte + 300;
                    } else {
                        new_end = source_document.content.len();
                    }
                    (new_start, new_end) =
                        adjust_byte_positions(new_start, new_end, &line_end_indices);

                    // print the new start and end
                    println!("---new_start: {:?}, new_end: {:?}", new_start, new_end);
                    let content = source_document.content[new_start..new_end].to_string();
                    // print content
                    println!(
                        "--- nodexxx content: symbol: {} \n{:?}\n",
                        code_meta.symbol, content
                    );
                } else {
                    let node_idx = node_idx.unwrap();

                    // Get the byte range of the found node.
                    let range: symbol::TextRange =
                        sg.graph[sg.value_of_definition(node_idx).unwrap_or(node_idx)].range();

                    // Adjust the starting byte to the beginning of the line.
                    new_start = range.start.byte - range.start.column;

                    // Determine the end byte based on the line end index or the range's end.
                    new_end = line_end_indices
                        .get(range.end.line)
                        .map(|l| *l as usize)
                        .unwrap_or(range.end.byte);

                    println!(
                        "Inside else adjusted start and end bytes: {:?}, {:?}",
                        new_start, new_end
                    );
                    // Convert byte positions back to line numbers to identify the extracted range's start and end lines.
                    let starting_line = get_line_number(new_start, &line_end_indices);
                    let ending_line = get_line_number(new_end, &line_end_indices);
                    println!(
                        "Inside else adjusted start and end lines: {:?}, {:?}",
                        starting_line, ending_line
                    );
                    // subtract starting and ending line
                    let mut total_lines = ending_line - starting_line;

                    if total_lines < 8 {
                        println!("---new_start: {:?}, new_end: {:?}", new_start, new_end);
                        // Adjustments for ensuring content context.

                        // Ensure the extracted content doesn't exceed the document's bounds.
                        let mut temp_new_end = new_end.clone();
                        if new_end + 300 > source_document.content.len() {
                            new_end = source_document.content.len();
                            temp_new_end = source_document.content.len() - 2;
                        } else {
                            new_end += 300;
                            temp_new_end += 300;
                        }
                        (new_start, new_end) =
                            adjust_byte_positions(new_start, temp_new_end, &line_end_indices);
                    } else if total_lines > 20 {
                        // If the extracted content exceeds 25 lines, change the end byte to the end of the 25th line.
                        new_end = line_end_indices
                            .get(starting_line + 20)
                            .map(|l| *l as usize)
                            .unwrap_or(new_end);
                    }
                    // print new start and end
                }

                // find starting line and ending line
                let ending_line = get_line_number(new_end, &line_end_indices);
                let starting_line = get_line_number(new_start, &line_end_indices);

                // Extract the desired content slice from the source document.
                let content = source_document.content[new_start..new_end].to_string();

                // Construct the extracted content object.
                let extract_content = ExtractedContent {
                    path: path.clone(),
                    content,
                    start_byte: new_start,
                    end_byte: new_end,
                    start_line: starting_line,
                    end_line: ending_line,
                };

                // Store the extracted content in the results vector.
                results.push(extract_content);
            }
        }

        Ok(results)
    }

    pub async fn get_file_content(&self, path: &str) -> Result<Option<ContentDocument>> {
        // println!("fetching file content {}\n", path);
        let configuration = Config::new().unwrap();

        self.app_state.db_connection
            .get_file_from_quickwit(&configuration.repo_name, "relative_path", path)
            .await
    }
    // pub async fn get_file_content(&self, path: &str) -> Result<Option<ContentDocument>> {
    //     println!("executing file search {}\n", path);
    //     self.db
    //         .indexes
    //         .file
    //         .by_path(path)
    //         .await
    //         .with_context(|| format!("failed to read path: {}", path))
    // }

    pub async fn fuzzy_path_search<'a>(
        &'a self,
        query: &str,
    ) -> impl Iterator<Item = FileDocument> + 'a {
        println!("executing fuzzy search {}\n", query);
        let configuration = Config::new().unwrap();
        self.app_state.db_connection
            .fuzzy_path_match(&configuration.repo_name, "relative_path", query, 50)
            .await
    }
}

fn trim_history(
    mut history: Vec<llm_gateway::api::Message>,
) -> Result<Vec<llm_gateway::api::Message>> {
    const HEADROOM: usize = 2048;
    const HIDDEN: &str = "[HIDDEN]";

    let mut tiktoken_msgs = history.iter().map(|m| m.into()).collect::<Vec<_>>();

    while tiktoken_rs::get_chat_completion_max_tokens(ANSWER_MODEL, &tiktoken_msgs)? < HEADROOM {
        let _ = history
            .iter_mut()
            .zip(tiktoken_msgs.iter_mut())
            .position(|(m, tm)| match m {
                llm_gateway::api::Message::PlainText {
                    role,
                    ref mut content,
                } => {
                    if role == "assistant" && content != HIDDEN {
                        *content = HIDDEN.into();
                        tm.content = HIDDEN.into();
                        true
                    } else {
                        false
                    }
                }
                llm_gateway::api::Message::FunctionReturn {
                    role: _,
                    name: _,
                    ref mut content,
                } if content != HIDDEN => {
                    *content = HIDDEN.into();
                    tm.content = HIDDEN.into();
                    true
                }
                _ => false,
            })
            .ok_or_else(|| anyhow!("could not find message to trim"))?;
    }

    Ok(history)
}

#[derive(Debug, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Action {
    /// A user-provided query.
    Query(String),

    Path {
        query: String,
    },
    #[serde(rename = "none")]
    Answer {
        paths: Vec<usize>,
    },
    Code {
        query: String,
    },
    Proc {
        query: String,
        paths: Vec<usize>,
    },
}

impl Action {
    /// Deserialize this action from the GPT-tagged enum variant format.
    ///
    /// We convert (2 examples):
    ///
    /// ```text
    /// {"name": "Variant1", "args": {}}
    /// {"name": "Variant2", "args": {"a":123}}
    /// ```
    ///
    /// To:
    ///
    /// ```text
    /// {"Variant1": {}}
    /// {"Variant2": {"a":123}}
    /// ```
    ///
    /// So that we can deserialize using the serde-provided "tagged" enum representation.
    fn deserialize_gpt(call: &FunctionCall) -> Result<Self> {
        let mut map = serde_json::Map::new();
        map.insert(
            call.name.clone().unwrap(),
            serde_json::from_str(&call.arguments)?,
        );

        Ok(serde_json::from_value(serde_json::Value::Object(map))?)
    }
}

#[cfg(test)]
mod tests {
    use pretty_assertions::assert_eq;

    use super::*;

    #[test]
    fn test_trimming_history() {
        let long_string = "long string ".repeat(2000);
        let history = vec![
            llm_gateway::api::Message::system("foo"),
            llm_gateway::api::Message::user("bar"),
            llm_gateway::api::Message::assistant("baz"),
            llm_gateway::api::Message::user("box"),
            llm_gateway::api::Message::assistant(&long_string),
            llm_gateway::api::Message::user("fred"),
            llm_gateway::api::Message::assistant("thud"),
            llm_gateway::api::Message::user(&long_string),
            llm_gateway::api::Message::user("corge"),
        ];

        assert_eq!(
            trim_history(history).unwrap(),
            vec![
                llm_gateway::api::Message::system("foo"),
                llm_gateway::api::Message::user("bar"),
                llm_gateway::api::Message::assistant("[HIDDEN]"),
                llm_gateway::api::Message::user("box"),
                llm_gateway::api::Message::assistant("[HIDDEN]"),
                llm_gateway::api::Message::user("fred"),
                llm_gateway::api::Message::assistant("thud"),
                llm_gateway::api::Message::user(&long_string),
                llm_gateway::api::Message::user("corge"),
            ]
        );
    }
}
