use std::collections::HashSet;

use anyhow::Result;
use tracing::instrument;

use crate::agent::agent::Agent;

use crate::agent::exchange::{SearchStep, Update};

impl Agent {
    #[instrument(skip(self))]
    pub async fn path_search(&mut self, query: &String) -> Result<String> {
        let last_function_call_id = self.last_function_call_id.clone();
        self.update(Update::StartStep(SearchStep::Path {
            id: last_function_call_id,
            query: query.clone(),
            response: String::new(),
        }))?;

        // First, perform a lexical search for the path
        let mut paths = self
            .fuzzy_path_search(query)
            .await
            .map(|c| c.relative_path)
            .collect::<HashSet<_>>() // TODO: This shouldn't be necessary. Path search should return unique results.
            .into_iter()
            .collect::<Vec<_>>();

        // If there are no lexical results, perform a semantic search.
        if paths.is_empty() {
            let semantic_paths = self
                .semantic_search(query.into(), 30, 0, 0.0, true)
                .await?
                .into_iter()
                .map(|chunk| chunk.relative_path)
                .collect::<HashSet<_>>()
                .into_iter()
                .collect();

            paths = semantic_paths;
        }

        let mut paths = paths
            .iter()
            .map(|p| (self.get_path_alias(p), p.to_string()))
            .collect::<Vec<_>>();
        paths.sort_by(|a: &(usize, String), b| a.0.cmp(&b.0)); // Sort by alias

        let response = paths
            .iter()
            .map(|(alias, path)| format!("{}: {}", alias, path))
            .collect::<Vec<_>>()
            .join("\n");

        let last_function_call_id = self.last_function_call_id.clone();
        self.update(Update::ReplaceStep(SearchStep::Path {
            id: last_function_call_id.clone(),
            query: query.clone(),
            response: response.clone(),
        }))?;
        let result = "OK";
        Ok(result.to_string())
    }
}
