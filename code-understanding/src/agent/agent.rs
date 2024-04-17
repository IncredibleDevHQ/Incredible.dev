use log::{debug, error};
use serde::{Deserialize, Serialize};
use std::hash::Hash;
use std::sync::Arc;
use std::time::Duration;
use tracing::instrument;

use crate::{config::get_ai_gateway_config, AppState};
use anyhow::{anyhow, Context, Result};

use common::{
    ai_util::{call_llm, find_first_function_call},
    prompts,
};

use crate::agent::exchange::{Exchange, SearchStep, Update};
use ai_gateway::message::message::{self, MessageRole};
use ai_gateway::{
    config::AIGatewayConfig,
    function_calling::{Function, FunctionCall},
};

use crate::agent::transform;
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

/// A collection of modules that each add methods to `Agent`.
///
/// These methods correspond to `Action` handlers, and often have supporting methods and supporting
/// functions, that are local to their own implementation. These modules also have independent
/// tests.

pub const ANSWER_MODEL: &str = "gpt-4-0613";

#[allow(unused)]
pub enum AgentError {
    Timeout(Duration),
    Processing(anyhow::Error),
}

pub struct Agent {
    pub repo_name: String,
    pub app_state: Arc<AppState>,
    pub exchanges: Vec<Exchange>,
    pub ai_gateway: AIGatewayConfig,
    pub query_id: String,
    pub last_function_call_id: Option<String>,
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
            log::debug!("Dropping agent");
        }
    }
}

// gien the start and end byte, readjust them to cover the entire start line and the entire end line.
#[allow(unused)]
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

pub fn get_line_number(byte: usize, line_end_indices: &[usize]) -> usize {
    // if byte is zero, return 0
    if byte == 0 {
        return 0;
    }
    let line = line_end_indices
        .iter()
        .position(|&line_end_byte| (line_end_byte as usize) >= byte)
        .unwrap_or(0);

    return line;
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
        //log::debug!("update {:?}", update);
        Ok(())
    }

    pub fn get_final_anwer(&self) -> &Exchange {
        self.exchanges.last().expect("answer was not set")
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
    pub async fn step(&mut self, action: Action, exchange_exists: bool) -> Result<Option<Action>> {
        log::debug!("\ninside step {:?}\n", action);
        if !exchange_exists {
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
        } else {
            debug!("exchange exists.");
        }

        let functions = serde_json::from_value::<Vec<Function>>(
            prompts::functions(self.paths().next().is_some()), // Only add proc if there are paths in context
        )
        .unwrap();

        let mut history = vec![message::Message::system(&prompts::system(self.paths()))];
        history.extend(self.history()?);

        log::debug!("full history:\n {:?}", history);

        //let trimmed_history = trim_history(history.clone())?;

        //log::debug!("trimmed history:\n {:?}", trimmed_history);
        // call the llm
        let llm_output = call_llm(
            &get_ai_gateway_config(),
            None,
            Some(history),
            Some(functions),
        )
        .await?;

        if let Some((function_to_call, id)) = find_first_function_call(&llm_output) {
            log::debug!("{:?} next action", function_to_call);
            let action = Action::deserialize_gpt(&function_to_call)
                .context("failed to deserialize LLM output")?;

            self.last_function_call_id = id;
            Ok(Some(action))
        } else {
            // return error if no function call is found.
            error!("No FunctionCall found.");
            return Err(anyhow!("No FunctionCall found."));
        }
        // print the next action picked.

        // log::debug!("full_history:\n {:?}\n", &history);
        //log::debug!("trimmed_history:\n {:?}\n", &trimmed_history);
        // log::debug!("last_message:\n {:?} \n", history.last());
        // log::debug!("functions:\n {:?} \n", &functions);
    }

    /// The full history of messages, including intermediate function calls
    fn history(&self) -> Result<Vec<message::Message>> {
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
                    .map(|q| message::Message::user(&q))
                    .ok_or_else(|| anyhow!("query does not have target"))?;

                let steps = e.search_steps.iter().flat_map(|s| {
                    let (id, name, arguments) = match s {
                        SearchStep::Path { id, query, .. } => (
                            id,
                            "path".to_owned(),
                            format!("{{\n \"query\": \"{query}\"\n}}"),
                        ),
                        SearchStep::Code { id, query, .. } => (
                            id,
                            "code".to_owned(),
                            format!("{{\n \"query\": \"{query}\"\n}}"),
                        ),
                        SearchStep::Proc {
                            id, query, paths, ..
                        } => (
                            id,
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
                        message::Message::function_call(
                            id.clone(),
                            &FunctionCall {
                                name: name.clone(),
                                arguments,
                            },
                        ),
                        message::Message::function_return(id.clone(), &name, &s.get_response()),
                        //message::Message::user(FUNCTION_CALL_INSTRUCTION),
                    ]
                });

                let answer = match e.answer() {
                    // NB: We intentionally discard the summary as it is redundant.
                    Some((answer, _conclusion, answer_id)) => {
                        let encoded = transform::encode_summarized(answer, None, "gpt-3.5-turbo")?;
                        Some(message::Message::function_return(
                            Some(answer_id.to_string()),
                            "none",
                            &encoded,
                        ))
                    }

                    None => None,
                };

                acc.extend(
                    std::iter::once(query)
                        //.chain(vec![message::Message::user(FUNCTION_CALL_INSTRUCTION)])
                        .chain(steps)
                        .chain(answer.into_iter()),
                );
                Ok(acc)
            })?;
        Ok(history)
    }

    pub async fn get_file_content(
        &self,
        base_url: &str,
        path: &str,
    ) -> Result<Option<ContentDocument>> {
        self.app_state
            .db_connection
            .get_file_from_quickwit(base_url, &self.repo_name, "relative_path", path)
            .await
    }

    pub async fn fuzzy_path_search<'a>(
        &'a self,
        query: &str,
    ) -> impl Iterator<Item = FileDocument> + 'a {
        log::debug!("executing fuzzy search {}\n", query);
        self.app_state
            .db_connection
            .fuzzy_path_match(&self.repo_name, "relative_path", query, 50)
            .await
    }
}

fn trim_history(mut history: Vec<message::Message>) -> Result<Vec<message::Message>> {
    const HEADROOM: usize = 100000;
    const HIDDEN: &str = "[HIDDEN]";

    let mut tiktoken_msgs = history.iter().map(|m| m.into()).collect::<Vec<_>>();

    while tiktoken_rs::get_chat_completion_max_tokens(ANSWER_MODEL, &tiktoken_msgs)? < HEADROOM {
        debug!("Trimming history");
        let _ = history
            .iter_mut()
            .zip(tiktoken_msgs.iter_mut())
            .position(|(m, tm)| match m {
                message::Message::PlainText {
                    role,
                    ref mut content,
                } => {
                    if *role == MessageRole::Assistant && content != HIDDEN {
                        *content = HIDDEN.into();
                        tm.content = HIDDEN.into();
                        true
                    } else {
                        false
                    }
                }
                message::Message::FunctionReturn {
                    id: _,
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
        map.insert(call.name.clone(), serde_json::from_str(&call.arguments)?);

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
            message::Message::system("foo"),
            message::Message::user("bar"),
            message::Message::assistant("baz"),
            message::Message::user("box"),
            message::Message::assistant(&long_string),
            message::Message::user("fred"),
            message::Message::assistant("thud"),
            message::Message::user(&long_string),
            message::Message::user("corge"),
        ];

        assert_eq!(
            trim_history(history).unwrap(),
            vec![
                message::Message::system("foo"),
                message::Message::user("bar"),
                message::Message::assistant("[HIDDEN]"),
                message::Message::user("box"),
                message::Message::assistant("[HIDDEN]"),
                message::Message::user("fred"),
                message::Message::assistant("thud"),
                message::Message::user(&long_string),
                message::Message::user("corge"),
            ]
        );
    }
}
