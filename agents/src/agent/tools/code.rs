use crate::agent::agent::Agent;
use crate::helpers::symbol_search::symbol_search;

use crate::agent::exchange::{CodeChunk, SearchStep, Update};
use anyhow::Result;
use tracing::instrument;

impl Agent {
    #[instrument(skip(self))]
    pub async fn code_search(&mut self, query: &String) -> Result<String> {
        self.update(Update::StartStep(SearchStep::Code {
            query: query.clone(),
            response: String::new(),
        }))?;

        println!("semantic search\n");

        let results_symbol = symbol_search(query, &self.repo_name).await;

        // log the error and return of there is error 
        if results_symbol.is_err() {
            let response = format!("Error validating if the collection exists: {}", results_symbol.err().unwrap());
            log::error!("Error validating if the collection exists: {}", response);
            // TODO: Fix the return type of this function return Result<String, Error> , and abort 
            // the agent flow on error.
            return Ok(response);
        }

        let code_snippet = results_symbol.unwrap();

        // println!("Size of semantic search: {}", results.len());

        let mut code_chunks = code_snippet
            .into_iter()
            .map(|chunk| {
                let relative_path = chunk.relative_path.clone(); // Clone relative_path
                CodeChunk {
                    path: relative_path,                              // Use the cloned relative_path
                    alias: self.get_path_alias(&chunk.relative_path), // Use the original relative_path for this call
                    snippet: chunk.snippets,
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

        println!("response: {}", response);
        self.update(Update::ReplaceStep(SearchStep::Code {
            query: query.clone(),
            response: response.clone(),
        }))?;

        Ok(response)
    }
}
