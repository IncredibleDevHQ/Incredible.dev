use crate::agent::agent::Agent;
use crate::agent::llm_gateway;
use futures::{stream, StreamExt, TryStreamExt};

use crate::parser::parser::Query;
use crate::search::payload::Payload;
use crate::search::ranking::{rank_symbol_payloads, symbol_weights};
use anyhow::{Error, Result};
use tracing::{info, instrument};
//use crate::agent::llm_gateway::api::Result;
use crate::agent::{
    exchange::{CodeChunk, SearchStep, Update},
    prompts,
};

const CODE_SEARCH_LIMIT: u64 = 10;
impl Agent {
    #[instrument(skip(self))]
    pub async fn code_search(&mut self, query: &String) -> Result<String> {
        self.update(Update::StartStep(SearchStep::Code {
            query: query.clone(),
            response: String::new(),
        }))
        .await?;

        let query_str = query.clone();
        // performing semantic search on the code chunks.

        let mut results = self
            .semantic_search(query.into(), CODE_SEARCH_LIMIT, 0, 0.0, true)
            .await?;
        let printResults: Vec<_> = results
            .clone()
            .into_iter()
            .map(|result| {
                println!(
                    "Before hyde {}, {}, {}",
                    result.relative_path, result.start_line, result.end_line
                );
                if result.relative_path == "server/bleep/src/webserver/config.rs" {
                    println!("config.rs found\n{}\n", result.text);
                }
            })
            .collect();

        // performing semantic search on the symbols.
        println!("semantic search\n");
        let mut results_symbol: Vec<crate::search::payload::SymbolPayload> = self
            .semantic_search_symbol(query.into(), CODE_SEARCH_LIMIT, 0, 0.0, true)
            .await?;

        // for top 3 symbols, perform semantic search using the symbol as a query and print the results with good formatting
        for symbol in results_symbol.iter().take(10) {
            println!(
                "Symbol semantic search on chunk: Symbol: {}, Score: {:?}, Relative paths: {:?}, Types: {:?}, isglobals:{:?}, node_types:{:?}",
                symbol.symbol, symbol.score, symbol.relative_paths, symbol.symbol_types, symbol.is_globals, symbol.node_kinds,
            );
            // let query = &symbol.symbol;
            // let mut results_symbol: Vec<crate::search::payload::Payload> = self
            //     .semantic_search(query.into(), CODE_SEARCH_LIMIT, 0, 0.0, true)
            //     .await?;
            // let printResults: Vec<_> = results_symbol
            //     .clone()
            //     .into_iter()
            //     .map(|result| {
            //         println!(
            //             "\nsymbol {}, {}, {}, {:?}",
            //             result.relative_path, result.start_line, result.end_line, result.relative_path,
            //         );
            //     })
            //     .collect();
        }
   
        let ranked_symbols = rank_symbol_payloads(&results_symbol);


        // print the top 5 ranked symbols
        // dont print the history, print result of the values
        // for each ranked symbol, print the data inside the vector of code extract meta
       
        let printResults: Vec<_> = ranked_symbols
            .clone()
            .into_iter()
            .map(|result| {
                println!(
                    "ranked pathuuuuuuuuuuuu\n {}, {}",
                    result.path, result.score
                );
                // iterate through code extract meta and print the symbol and score 
                for code_extract_meta in result.code_extract_meta.iter() {
                    println!(
                        "--code extract meta: {}, {}",
                        code_extract_meta.symbol,  code_extract_meta.score,
                    );
                }

            })
            .collect();

        // call self.get_scope_graph on top 3 paths from ranked_symbpls
       let extracted_chunks = self.process_paths(ranked_symbols.iter().cloned().take(10).collect()).await?;

    // print the extracted chunks
    let printResults: Vec<_> = extracted_chunks
        .clone()
        .into_iter()
        .map(|result| {
            println!(
                "extracted chunks- {}, {}, {}, \n{}\n",
                result.path, result.start_line, result.end_line, result.content
            );
        })
        .collect();



        let printResults: Vec<_> = results_symbol
            .clone()
            .into_iter()
            .map(|result| {
                println!(
                    "{}, {:?}, {:?}",
                    result.symbol, result.is_globals, result.relative_paths,
                );
            })
            .collect();

        println!("Size of semantic search: {}", results.len());

        // let hyde_docs = self.hyde(query).await?;
        // // perform hyde semantic search
        // let hyde_results = self.perform_hyde_semantic_search(hyde_docs).await?;


        // Process the `results_symbol` list to extract the most relevant symbol information for each entry.
        //
        // For each entry in `results_symbol`:
        // 1. Enumerate over the `symbol_types` to pair each symbol with its index.
        // 2. Determine the score of each symbol using the `symbol_weights` function:
        //    - If the symbol exists in the `symbol_weights` hashmap, use its score.
        //    - If the symbol doesn't exist, default to the score of the "unknown" symbol.
        // 3. Find the symbol with the highest score using the `max_by` function.
        // 4. Transform the result into a tuple containing:
        //    - The main symbol of the entry.
        //    - The symbol type with the highest score.
        //    - The corresponding language ID for the highest scoring symbol type.
        //    - The overall score of the entry.
        //
        // The result is a list of tuples, where each tuple provides the most relevant symbol information for its corresponding entry.

        // let top_symbol_types = results_symbol
        //     .into_iter()
        //     .filter_map(|result| {
        //         // Find the symbol with the highest score
        //         result
        //             .symbol_types
        //             .iter()
        //             .enumerate()
        //             .max_by(|(i1, symbol1), (i2, symbol2)| {
        //                 let symbol_score_hashmap = symbol_weights();
        //                 let score1 = *symbol_score_hashmap
        //                     .get(&symbol1 as &str)
        //                     .unwrap_or_else(|| &symbol_score_hashmap["unknown"]);
        //                 let score2 = *symbol_score_hashmap
        //                     .get(&symbol2 as &str)
        //                     .unwrap_or_else(|| &symbol_score_hashmap["unknown"]);
        //                 score1
        //                     .partial_cmp(&score2)
        //                     .unwrap_or(std::cmp::Ordering::Equal)
        //             })
        //             .map(|(i, _)| {
        //                 // Transform the result into the desired tuple
        //                 (
        //                     result.symbol.clone(),
        //                     result.symbol_types[i].clone(),
        //                     result.lang_ids[i].clone(),
        //                     result.score,
        //                 )
        //             })
        //     })
        //     .collect::<Vec<_>>();

        // // print the top symbols
        // println!("Top symbols: {:?}", top_symbol_types);

        // // Use the first value from the top symbol types to perform a hyde v2 search
        // let top_symbol = top_symbol_types.first().unwrap();

        // // create new query using top three symbols
        // let top_three_query_Str = &format!(
        //     "{} {} {} {}",
        //     query_str, top_symbol.0, top_symbol.1, top_symbol.2
        // );
        // let new_query_str = &format!("{} {}", query_str, top_symbol.0);
        // let mut results = self
        //     .semantic_search(new_query_str.into(), CODE_SEARCH_LIMIT, 0, 0.0, true)
        //     .await?;
        // let printResults: Vec<_> = results
        //     .clone()
        //     .into_iter()
        //     .map(|result| {
        //         println!(
        //             "With new query str {}, {}, {}",
        //             result.relative_path, result.start_line, result.end_line
        //         );
        //     })
        //     .collect();

        // let mut results = self
        //     .semantic_search(top_three_query_Str.into(), CODE_SEARCH_LIMIT, 0, 0.0, true)
        //     .await?;
        // let printResults: Vec<_> = results
        //     .clone()
        //     .into_iter()
        //     .map(|result| {
        //         println!(
        //             "With new query triple str {}, {}, {}",
        //             result.relative_path, result.start_line, result.end_line
        //         );
        //     })
        //     .collect();

        // let hyde_docs_v2 = self
        //     .hyde_v2(query, &top_symbol.2, &top_symbol.0, &top_symbol.1)
        //     .await?;
        // perform hyde semantic search v2
        // let hyde_results_v2 = self.perform_hyde_semantic_search(hyde_docs_v2).await?;
        // // print the hyde results v2
        // let printResults: Vec<_> = hyde_results_v2
        //     .clone()
        //     .into_iter()
        //     .map(|result| {
        //         println!(
        //             "v2 Hyde {}, {}, {}",
        //             result.relative_path, result.start_line, result.end_line
        //         );
        //     })
        //     .collect();

        // // Use the top 3 symbols to perform a hyde v3 search
        // let top_symbols = top_symbol_types
        //     .into_iter()
        //     .take(3)
        //     .map(|symbol| {
        //         //println!("Symbol: {}, Score: {}", symbol.0, symbol.1);
        //         (symbol.2, symbol.0, symbol.1)
        //     })
        //     .collect::<Vec<_>>();

        // let hyde_docs_v3 = self.hyde_v3(query, top_symbols).await?;
        // // perform hyde semantic search v3
        // let hyde_results_v3 = self.perform_hyde_semantic_search(hyde_docs_v3).await?;
        // // print the hyde results v3
        // let printResults: Vec<_> = hyde_results_v3
        //     .clone()
        //     .into_iter()
        //     .map(|result| {
        //         println!(
        //             "v3 Hyde {}, {}, {}",
        //             result.relative_path, result.start_line, result.end_line
        //         );
        //     })
        //     .collect();

        //results.extend(hyde_results_v2);
        // let mut chunks = results
        //     .into_iter()
        //     .map(|chunk| {
        //         let relative_path = chunk.relative_path;

        //         CodeChunk {
        //             path: relative_path.clone(),
        //             alias: self.get_path_alias(&relative_path),
        //             snippet: chunk.text,
        //             start_line: chunk.start_line as usize,
        //             end_line: chunk.end_line as usize,
        //         }
        //     })
        //     .collect::<Vec<_>>();

        // create codeChunks from the extracted_chunks and append to chunks
        let mut codeChunks = extracted_chunks
            .into_iter()
            .map(|chunk| {
                let relative_path = chunk.path;

                CodeChunk {
                    path: relative_path.clone(),
                    alias: self.get_path_alias(&relative_path),
                    snippet: chunk.content,
                    start_line: chunk.start_line as usize,
                    end_line: chunk.end_line as usize,
                }
            })
            .collect::<Vec<_>>();

        // test here.
        //chunks.append(&mut codeChunks);

        codeChunks.sort_by(|a, b| a.alias.cmp(&b.alias).then(a.start_line.cmp(&b.start_line)));

        for chunk in codeChunks.iter().filter(|c| !c.is_empty()) {
            //println!("Code chunks from semantic search");
            self.exchanges
                .last_mut()
                .unwrap()
                .code_chunks
                .push(chunk.clone())
        }

        let response = codeChunks
            .iter()
            .filter(|c| !c.is_empty())
            .map(|c| c.to_string())
            .collect::<Vec<_>>()
            .join("\n\n");

        println!("response: {}", response);
        self.update(Update::ReplaceStep(SearchStep::Code {
            query: query.clone(),
            response: response.clone(),
        }))
        .await?;

        Ok(response)
    }

    // take the hyde document and perform semantic search on it.
    async fn perform_hyde_semantic_search(&self, hyde_docs: Vec<String>) -> Result<Vec<Payload>> {
        let hyde_doc = hyde_docs.first().unwrap().into();
        // print the hyde document
        println!("hyde doc v1: {:?}", hyde_doc);
        let hyde_results = self
            .semantic_search(hyde_doc, CODE_SEARCH_LIMIT, 0, 0.3, true)
            .await?;

        println!("Hyde semantic results ");
        let tranformed: Vec<_> = hyde_results
            .clone()
            .into_iter()
            .map(|result| {
                println!(
                    "{}, {}, {}",
                    result.relative_path, result.start_line, result.end_line
                );
            })
            .collect();
        Ok(hyde_results)
    }
    /// Hypothetical Document Embedding (HyDE): https://arxiv.org/abs/2212.10496
    ///
    /// This method generates synthetic documents based on the query. These are then
    /// parsed and code is extracted. This has been shown to improve semantic search recall.
    async fn hyde(&self, query: &str) -> Result<Vec<String>> {
        let prompt = vec![llm_gateway::api::Message::system(
            &prompts::hypothetical_document_prompt(query),
        )];

        tracing::trace!(?query, "generating hyde docs");

        let response = self
            .llm_gateway
            .clone()
            .model("gpt-3.5-turbo-0613")
            .chat(&prompt, None)
            .await?;

        let choices = response.choices[0].clone();
        let mut response_message = choices.message.content.unwrap();
        tracing::trace!("parsing hyde response");

        let documents = prompts::try_parse_hypothetical_documents(&response_message);

        for doc in documents.iter() {
            info!(?doc, "got hyde doc");
        }

        Ok(documents)
    }
    /// Hypothetical Document Embedding (HyDE): https://arxiv.org/abs/2212.10496
    ///
    /// This method generates synthetic documents based on the query. These are then
    /// parsed and code is extracted. This has been shown to improve semantic search recall.
    async fn hyde_v2(
        &self,
        query: &str,
        language: &str,
        symbol_name: &str,
        symbol_type: &str,
    ) -> Result<Vec<String>> {
        let hyde_prompt_v2 =
            &prompts::hypothetical_document_prompt_v2(query, language, symbol_name, symbol_type);

        println!("hyde prompt v2: {}", hyde_prompt_v2);

        // generate hyde document using prompt v2 by calling llm
        let prompt = vec![llm_gateway::api::Message::system(hyde_prompt_v2)];

        let response = self
            .llm_gateway
            .clone()
            .model("gpt-4")
            .chat(&prompt, None)
            .await?;
        let choices = response.choices[0].clone();
        let mut response_message_v2 = choices.message.content.unwrap();
        // print hyde document
        println!("hyde response v2: {}", response_message_v2);

        tracing::trace!("parsing hyde response");

        let documents_v2 = prompts::try_parse_hypothetical_documents(&response_message_v2);

        for doc in documents_v2.iter() {
            info!(?doc, "got hyde doc v2");
        }

        Ok(documents_v2)

        //Ok(vec![documents, documents_v2].into_iter().flatten().collect())
    }

    async fn hyde_v3(
        &self,
        query: &str,
        // takes an array of tuples containing language, symbol_name, symbol_type
        // Vec< language: &str,symbol_name: &str, symbol_type: &str>,
        symbol_tuples: Vec<(String, String, String)>,
    ) -> Result<Vec<String>> {
        let hyde_prompt_v3 = &prompts::hypothetical_document_prompt_v3(query, symbol_tuples);

        println!("hyde prompt v3: {}", hyde_prompt_v3);

        // generate hyde document using prompt v2 by calling llm
        let prompt = vec![llm_gateway::api::Message::system(hyde_prompt_v3)];

        let response = self
            .llm_gateway
            .clone()
            .model("gpt-4")
            .chat(&prompt, None)
            .await?;
        let choices = response.choices[0].clone();
        let mut response_message_v2 = choices.message.content.unwrap();
        // print hyde document
        println!("hyde response v3: {}", response_message_v2);

        tracing::trace!("parsing hyde response");

        let documents_v3 = prompts::try_parse_hypothetical_documents(&response_message_v2);

        for doc in documents_v3.iter() {
            info!(?doc, "got hyde doc v3");
        }

        Ok(documents_v3)

        //Ok(vec![documents, documents_v2].into_iter().flatten().collect())
    }
}
