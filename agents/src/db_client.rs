use std::collections::{HashMap, HashSet};
use std::hash::{Hash, Hasher};

use crate::agent::agent::{ContentDocument, FileDocument};
use crate::config::Config;
use crate::helpers::build_fuzzy_regex_filter::build_fuzzy_regex_filter;
use crate::helpers::case_permutations::case_permutations;
use crate::helpers::trigrams::trigrams;
use crate::search;
use crate::Configuration;
use bincode::config;
use compact_str::CompactString;
use futures::future;

use anyhow::Result;

use serde::{Deserialize, Serialize};
use serde_json;

use reqwest::{Client, Error};

pub struct DbConnect {
    pub semantic: search::semantic::Semantic,
    pub http_client: Client,
}

#[derive(Debug, Serialize, Deserialize)]
struct BodyRes {
    query: String,
    max_hits: i32,
}

#[derive(Debug, Serialize, Deserialize)]
struct ApiResponse {
    num_hits: i32,            // Change the type to i32 or another appropriate numeric type
    elapsed_time_micros: i64, // Change the type to i32 or another appropriate numeric type
    hits: Vec<ResultItem>,
    errors: Vec<String>,
}

#[derive(Debug, Serialize, Deserialize)]
struct ResultItem {
    relative_path: String,
    repo_name: String,
    lang: Option<String>,
    content: String,
    symbols: String,
    line_end_indices: Vec<u8>,
    symbol_locations: Vec<u8>,
    is_directory: bool,
    last_commit: String,
    repo_ref: String,
    repo_disk_path: String,
    unique_hash: String,
}

impl DbConnect {
    pub async fn new(config: Configuration) -> Result<Self, anyhow::Error> {
        let http_client = reqwest::Client::new();

        let semantic = search::semantic::Semantic::initialize(config).await;
        match semantic {
            Ok(semantic) => Ok(Self {
                semantic,
                http_client,
            }),
            Err(err) => {
                println!("Failed to initialize semantic search: {}", err);
                Err(err.into())
            }
        }
    }

    pub async fn get_file_from_quickwit(
        &self,
        index_name: &str,
        search_field: &str,
        search_query: &str,
    ) -> Result<Option<ContentDocument>> {
        let response_array = self
            .search_quickwit(index_name, search_field, search_query)
            .await?;

        let cloned_response_array = response_array.clone(); // Clone the response_array

        let paths: Vec<_> = cloned_response_array
            .into_iter()
            .map(|c| c.relative_path)
            .collect::<HashSet<_>>() // Removes duplicates
            .into_iter()
            .collect::<Vec<_>>();
        //println!("Quick wit paths: {:?}", paths);
        //println!("search_query: {}", search_query);

        Ok(response_array)
    }

    pub async fn search_quickwit(
        &self,
        index_name: &str,
        search_field: &str,
        search_query: &str,
    ) -> Result<Option<ContentDocument>, Error> {
        let configuration = Config::new().unwrap();
        let base_url = configuration.quickwit_url.clone();

        let query = if !search_field.is_empty() {
            format!("{}:{}", search_field, search_query)
        } else {
            search_query.to_owned()
        };

        let json_data = BodyRes {
            query,
            max_hits: 10,
        };

        let json_string = serde_json::to_string(&json_data).expect("Failed to serialize object");

        let url = format!("{}/api/v1/{}/search", base_url, index_name);

        let response = self
            .http_client
            .post(url)
            .header("Content-Type", "application/json")
            .body(json_string)
            .send()
            .await?;

        let mut response_array: Vec<ContentDocument> = Vec::new();

        if response.status().is_success() {
            let response_text = response.text().await?;

            let parsed_response: Result<ApiResponse, serde_json::Error> =
                serde_json::from_str(&response_text);

            match parsed_response {
                Ok(api_response) => {
                    for result_item in api_response.hits {
                        if search_query == result_item.relative_path {
                            println!("Found a match: {}", search_query);
                            response_array.push(ContentDocument {
                                relative_path: result_item.relative_path,
                                repo_name: result_item.repo_name,
                                lang: result_item.lang,
                                content: result_item.content,
                                repo_ref: result_item.repo_ref,
                                line_end_indices: result_item.line_end_indices,
                                symbol_locations: result_item.symbol_locations,
                                symbols: result_item.symbols,
                            });
                        }
                    }
                }
                Err(err) => {
                    println!("Failed to parse JSON response: {}", err);
                }
            }
        } else {
            println!("Request was not successful: {}", response.status());
        }

        if !response_array.is_empty() {
            Ok(Some(response_array[0].clone())) // Return the first ContentDocument
        } else {
            Ok(None) // No ContentDocument found
        }
    }

    async fn search_api(
        &self,
        index_name: &str,
        search_field: &str,
        search_query: &str,
    ) -> Result<Vec<FileDocument>, Error> {
        let client = Client::new();
        let configuration = Config::new().unwrap();
        let base_url = configuration.quickwit_url.clone();

        println!("search_query {}", search_query);

        let query = if !search_field.is_empty() {
            format!("{}:{}", search_field, search_query)
        } else {
            search_query.to_owned()
        };

        let json_data = BodyRes {
            query,
            max_hits: 100,
        };

        let json_string = serde_json::to_string(&json_data).expect("Failed to serialize object");

        let url = format!("{}/api/v1/{}/search", base_url, index_name);

        let response = client
            .post(url)
            .header("Content-Type", "application/json")
            .body(json_string)
            .send()
            .await?;

        let mut response_array: Vec<FileDocument> = Vec::new();

        if response.status().is_success() {
            let response_text = response.text().await?;

            let parsed_response: Result<ApiResponse, serde_json::Error> =
                serde_json::from_str(&response_text);

            match parsed_response {
                Ok(api_response) => {
                    for result_item in api_response.hits {
                        response_array.push(FileDocument {
                            relative_path: result_item.relative_path,
                            repo_name: result_item.repo_name,
                            lang: result_item.lang,
                            repo_ref: result_item.repo_ref,
                        });
                    }
                }
                Err(err) => {
                    println!("Failed to parse JSON response: {}", err);
                }
            }
        } else {
            println!("Request was not successful: {}", response.status());
        }

        Ok(response_array)
    }

    async fn search_with_async(
        &self,
        index_name: &str,
        search_field: &str,
        token: CompactString,
    ) -> Result<Vec<FileDocument>, Error> {
        let result = self
            .search_api(index_name, search_field, token.as_str())
            .await?;

        // let cloned_response_array = result.clone(); // Clone the response_array

        Ok(result)
    }

    pub async fn fuzzy_path_match(
        &self,
        index_name: &str,
        search_field: &str,
        search_query: &str,
        limit: usize,
    ) -> impl Iterator<Item = FileDocument> {
        let mut counts: HashMap<FileDocument, usize> = HashMap::new();

        let hits = trigrams(search_query)
            .flat_map(|s| case_permutations(s.as_str()))
            .chain(std::iter::once(search_query.to_owned().into())); // Pass token as a reference

        // Iterate over counts and populate file_documents
        for hit in hits {
            // println!("hit: {:?}\n", hit.clone());
            let result = self
                .search_with_async(index_name, search_field, hit.clone().into())
                .await;
            //println!("res: {:?}\n", result);
            for res in result.unwrap() {
                // Check if the key exists in the HashMap
                if let Some(entry) = counts.get_mut(&res.clone()) {
                    // The key exists, increment its value
                    *entry += 1;
                } else {
                    // The key doesn't exist, insert it with an initial value of 0
                    counts.insert(res.clone(), 0);
                }
            }
        }

        // Convert the HashMap into a Vec<(FileDocument, usize)>
        let mut new_hit: Vec<(FileDocument, usize)> = counts.into_iter().collect();

        new_hit.sort_by(|(this_doc, this_count), (other_doc, other_count)| {
            let order_count_desc = other_count.cmp(this_count);
            let order_path_asc = this_doc
                .relative_path
                .as_str()
                .cmp(other_doc.relative_path.as_str());

            order_count_desc.then(order_path_asc)
        });

        let regex_filter = build_fuzzy_regex_filter(search_query);

        // if the regex filter fails to build for some reason, the filter defaults to returning
        // false and zero results are produced
        // let result = new_hit
        //     .into_iter()
        //     .map(|(doc, _)| doc)
        //     .filter(move |doc| {
        //         regex_filter
        //             .as_ref()
        //             .map(|f| f.is_match(&doc.relative_path))
        //             .unwrap_or_default()
        //     })
        //     .filter(|doc| !doc.relative_path.ends_with('/')) // omit directories
        //     .take(limit);

        let mut filterd_hits = Vec::new();

        match regex_filter {
            Some(f) => {
                for res in new_hit {
                    if f.is_match(&res.0.relative_path) {
                        filterd_hits.push(res.0);
                    }
                }
            }
            None => {}
        }

        let result = filterd_hits.into_iter().take(limit);

        result
    }
}
