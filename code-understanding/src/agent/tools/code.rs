use crate::agent::agent::Agent;
use crate::helpers::symbol_search::symbol_search;

use crate::agent::exchange::{CodeChunk, SearchStep, Update};
use anyhow::Result;
use tracing::instrument;

use log::{error, debug};

impl Agent {
    #[instrument(skip(self))]
    pub async fn code_search(&mut self, query: &String) -> Result<String> {
        let last_function_call_id = self.last_function_call_id.clone();
        self.update(Update::StartStep(SearchStep::Code {
            id: last_function_call_id,
            query: query.clone(),
            response: String::new(),
        }))?;

        let results_symbol = symbol_search(query, &self.repo_name).await;

        // log and return the error 
        if results_symbol.is_err() {
            let err = results_symbol.err().unwrap();
            error!("Call to Symbol search API failed: {:?}", err);
            return Err(err);
        }

        // return error if the result is empty
        if results_symbol.as_ref().unwrap().is_empty() {
            let err = "No results found for symbol search API call";
            error!("{}", err);
            return Err(anyhow::Error::msg(err));
        }
        let code_snippet = results_symbol.unwrap();

        // log::debug!("Size of semantic search: {}", results.len());

        let mut code_chunks = code_snippet
            .into_iter()
            .map(|chunk| {
                let relative_path = chunk.path.clone(); // Clone relative_path
                CodeChunk {
                    path: relative_path,                              // Use the cloned relative_path
                    alias: self.get_path_alias(&chunk.path), // Use the original relative_path for this call
                    snippet: chunk.snippet,
                    start_line: chunk.start_line as usize,
                    end_line: chunk.end_line as usize,
                }
            })
            .collect::<Vec<_>>();

        code_chunks.sort_by(|a, b| a.alias.cmp(&b.alias).then(a.start_line.cmp(&b.start_line)));

        for chunk in code_chunks.iter().filter(|c| !c.is_empty()) {
            self.exchanges
                .last_mut()
                .unwrap()
                .code_chunks
                .push(chunk.clone())
        }

        let response = code_chunks
            .iter()
            .filter(|c| !c.is_empty())
            .map(|c| c.to_string())
            .collect::<Vec<_>>()
            .join("\n\n");

        log::debug!("response: {}", response);
        let last_function_call_id = self.last_function_call_id.clone();
        self.update(Update::ReplaceStep(SearchStep::Code {
            id: last_function_call_id,
            query: query.clone(),
            response: response.clone(),
        }))?;

        Ok(response)
    }
}
