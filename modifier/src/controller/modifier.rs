use crate::{
    agent::prompts, models::{CodeModifierRequest, ContextFile}, utils::llm_gateway, CONFIG
};
use common::{service_interaction::fetch_code_span, CodeChunk, CodeSpanRequest};
use futures::future::try_join_all;
use reqwest::StatusCode;
use std::{collections::HashMap, convert::Infallible};
use anyhow::Result;

#[derive(serde::Serialize, serde::Deserialize, Clone, Debug, PartialEq)]
struct CodeSnippets {
    path: String,
    repo: String,
    code_chunks: Vec<CodeChunk>,
}

pub async fn handle_modify_code(
    request: CodeModifierRequest
) -> Result<impl warp::Reply, Infallible> {
    let code_snippets = match get_code_snippets(request.clone(), CONFIG.code_search_url.clone()).await {
        Ok(code_snippets) => code_snippets,
        Err(e) => {
            log::error!("Failed to fetch code snippets: {}", e);
            return Ok(warp::reply::with_status(warp::reply::json(&format!("Error: Failed to fetch code snippets")), StatusCode::INTERNAL_SERVER_ERROR))
        },
    };
    let context = match generate_llm_context(code_snippets.clone(), request.context_files.clone()) {
        Ok(context) => context,
        Err(e) => {
            log::error!("Failed to generate LLM context: {}", e);
            return Ok(warp::reply::with_status(warp::reply::json(&format!("Error: Failed to generate LLM context")), StatusCode::INTERNAL_SERVER_ERROR))
        },
    };

    // TODO: Refactor llm gateway to be a common package and log the OpenAI request and response.
    let llm_gateway = llm_gateway::Client::new(&CONFIG.openai_url.clone())
        .temperature(0.0)
        .bearer(CONFIG.openai_api_key.clone())
        .model(&CONFIG.openai_model.clone());

    let system_prompt = prompts::diff_prompt(&context.clone());
    let user_message = format!("Create a patch for the task \"{}\".\n\n\nHere is the solution:\n\n{}", request.user_query, request.assistant_query);

    let messages = vec![llm_gateway::api::Message::system(&system_prompt), llm_gateway::api::Message::user(&user_message)];

    let response = match llm_gateway.chat(&messages, None).await {
        Ok(response) => Some(response),
        Err(_) => None,
    };

    Ok(warp::reply::with_status(
        warp::reply::json(&response),
        StatusCode::OK,
    ))
}

async fn get_code_snippets(
    request: CodeModifierRequest,
    code_search_url: String,
) -> Result<Vec<CodeSnippets>, anyhow::Error> {
    let url = format!("{}/span", code_search_url);

    let futures: Vec<_> = request
        .context_files
        .iter()
        .map(|context_file| {
            let url = url.clone();
            let code_span_request = CodeSpanRequest {
                path: context_file.path.clone(),
                branch: context_file.branch.clone(),
                repo: context_file.repo.clone(),
                ranges: Some(context_file.ranges.clone()),
                id: None,
            };
            let repo_clone = context_file.repo.clone();
            async move {
                match fetch_code_span(url, code_span_request)
                    .await {
                        Ok(code_chunks) => Ok((repo_clone, code_chunks)),
                        Err(e) => {
                            log::error!("Failed to fetch code span: {}", e); 
                            Ok((repo_clone, Vec::new()))
                        },
                    }
            }
        })
        .collect();

    let results = try_join_all(futures).await;

    results.and_then(|chunks| aggregate_code_chunks(chunks))
}

fn aggregate_code_chunks(
    results: Vec<(String, Vec<CodeChunk>)>,
) -> Result<Vec<CodeSnippets>, anyhow::Error> {
    let mut snippets_map: HashMap<(String, String), Vec<CodeChunk>> = HashMap::new();

    for (repo, code_chunks) in results {
        for chunk in code_chunks {
            let key = (repo.clone(), chunk.path.clone());
            snippets_map.entry(key).or_default().push(chunk);
        }
    }

    let code_snippets: Vec<CodeSnippets> = snippets_map
        .into_iter()
        .map(|((repo, path), code_chunks)| CodeSnippets {
            repo,
            path,
            code_chunks,
        })
        .collect();

    Ok(code_snippets)
}

fn generate_llm_context(snippets: Vec<CodeSnippets>, context: Vec<ContextFile>) -> Result<String> {
    let mut s = String::new();

    s += "#### PATHS ####\n";

    for file in context.iter().filter(|f| !f.hidden) {
        s += &format!("{}:{}\n", file.repo, file.path);
    }

    s += "#### CODE CHUNKS ####\n\n";

    for file in context.iter().filter(|f| !f.hidden) {
        let file_snippets = snippets
            .iter()
            .find(|snip| snip.repo == file.repo && snip.path == file.path)
            .unwrap();

        for chunk in file_snippets.code_chunks.iter() {
            s += &format!("### {}:{} ###\n{chunk}\n", file.repo, file.path);
        }
    }

    Ok(s)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_aggregate_code_chunks_empty() {
        let results = vec![];
        let expected = vec![];

        let output = aggregate_code_chunks(results).unwrap();
        assert_eq!(output, expected);
    }

    #[test]
    fn test_aggregate_code_chunks_single_chunk() {
        let results = vec![(
            "repo1".to_string(),
            vec![CodeChunk {
                path: "path/to/file.rs".to_string(),
                snippet: "fn main() {}".to_string(),
                start_line: 1,
                end_line: 3,
            }],
        )];
        let expected = vec![CodeSnippets {
            repo: "repo1".to_string(),
            path: "path/to/file.rs".to_string(),
            code_chunks: vec![CodeChunk {
                path: "path/to/file.rs".to_string(),
                snippet: "fn main() {}".to_string(),
                start_line: 1,
                end_line: 3,
            }],
        }];

        let output = aggregate_code_chunks(results).unwrap();
        assert_eq!(output, expected);
    }

    #[test]
    fn test_aggregate_code_chunks_multiple_chunks_same_repo_path() {
        let results = vec![(
            "repo1".to_string(),
            vec![
                CodeChunk {
                    path: "path/to/file.rs".to_string(),
                    snippet: "fn main() {}".to_string(),
                    start_line: 1,
                    end_line: 3,
                },
                CodeChunk {
                    path: "path/to/file.rs".to_string(),
                    snippet: "fn helper() {}".to_string(),
                    start_line: 5,
                    end_line: 7,
                },
            ],
        )];
        let expected = vec![CodeSnippets {
            repo: "repo1".to_string(),
            path: "path/to/file.rs".to_string(),
            code_chunks: vec![
                CodeChunk {
                    path: "path/to/file.rs".to_string(),
                    snippet: "fn main() {}".to_string(),
                    start_line: 1,
                    end_line: 3,
                },
                CodeChunk {
                    path: "path/to/file.rs".to_string(),
                    snippet: "fn helper() {}".to_string(),
                    start_line: 5,
                    end_line: 7,
                },
            ],
        }];

        let output = aggregate_code_chunks(results).unwrap();
        assert_eq!(output, expected);
    }

    #[test]
    fn test_aggregate_code_chunks_multiple_chunks_different_repos_paths() {
        let results = vec![
            (
                "repo1".to_string(),
                vec![
                    CodeChunk {
                        path: "path/to/file1.rs".to_string(),
                        snippet: "fn main() {}".to_string(),
                        start_line: 1,
                        end_line: 3,
                    },
                    CodeChunk {
                        path: "path/to/file1.rs".to_string(),
                        snippet: "fn main() {}".to_string(),
                        start_line: 6,
                        end_line: 7,
                    },
                    CodeChunk {
                        path: "path/to/file1.rs".to_string(),
                        snippet: "fn main() {}".to_string(),
                        start_line: 18,
                        end_line: 20,
                    },
                ],
            ),
            (
                "repo2".to_string(),
                vec![CodeChunk {
                    path: "path/to/file2.rs".to_string(),
                    snippet: "fn helper() {}".to_string(),
                    start_line: 5,
                    end_line: 7,
                }],
            ),
        ];
        let expected = vec![
            CodeSnippets {
                repo: "repo1".to_string(),
                path: "path/to/file1.rs".to_string(),
                code_chunks: vec![
                    CodeChunk {
                        path: "path/to/file1.rs".to_string(),
                        snippet: "fn main() {}".to_string(),
                        start_line: 1,
                        end_line: 3,
                    },
                    CodeChunk {
                        path: "path/to/file1.rs".to_string(),
                        snippet: "fn main() {}".to_string(),
                        start_line: 6,
                        end_line: 7,
                    },
                    CodeChunk {
                        path: "path/to/file1.rs".to_string(),
                        snippet: "fn main() {}".to_string(),
                        start_line: 18,
                        end_line: 20,
                    },
                ],
            },
            CodeSnippets {
                repo: "repo2".to_string(),
                path: "path/to/file2.rs".to_string(),
                code_chunks: vec![CodeChunk {
                    path: "path/to/file2.rs".to_string(),
                    snippet: "fn helper() {}".to_string(),
                    start_line: 5,
                    end_line: 7,
                }],
            },
        ];

        let output = aggregate_code_chunks(results).unwrap();
        assert_eq!(output.len(), expected.len());
        for snippet in expected {
            assert!(output.contains(&snippet));
        }
    }

    #[test]
    fn test_aggregate_code_chunks_multiple_chunks_different_paths() {
        let results = vec![
            (
                "repo1".to_string(),
                vec![CodeChunk {
                    path: "path/to/file1.rs".to_string(),
                    snippet: "fn main() {}".to_string(),
                    start_line: 1,
                    end_line: 3,
                }],
            ),
            (
                "repo1".to_string(),
                vec![CodeChunk {
                    path: "path/to/file2.rs".to_string(),
                    snippet: "fn helper() {}".to_string(),
                    start_line: 5,
                    end_line: 7,
                }],
            ),
        ];
        let expected = vec![
            CodeSnippets {
                repo: "repo1".to_string(),
                path: "path/to/file1.rs".to_string(),
                code_chunks: vec![CodeChunk {
                    path: "path/to/file1.rs".to_string(),
                    snippet: "fn main() {}".to_string(),
                    start_line: 1,
                    end_line: 3,
                }],
            },
            CodeSnippets {
                repo: "repo1".to_string(),
                path: "path/to/file2.rs".to_string(),
                code_chunks: vec![CodeChunk {
                    path: "path/to/file2.rs".to_string(),
                    snippet: "fn helper() {}".to_string(),
                    start_line: 5,
                    end_line: 7,
                }],
            },
        ];

        let output = aggregate_code_chunks(results).unwrap();
        assert_eq!(output.len(), expected.len());
        for snippet in expected {
            assert!(output.contains(&snippet));
        }
    }

    #[test]
    fn test_generate_llm_context_complex_snippets() {
        let context_files = vec![
            ContextFile {
                path: "src/lib.rs".to_string(),
                hidden: false,
                repo: "repo1".to_string(),
                branch: Some("main".to_string()),
                ranges: vec![],
            },
        ];

        let code_snippets = vec![
            CodeSnippets {
                path: "src/lib.rs".to_string(),
                repo: "repo1".to_string(),
                code_chunks: vec![
                    CodeChunk {
                        path: "src/lib.rs".to_string(),
                        snippet: 
                        "fn lib_function() -> bool {\n    // starts doing something\n    let result = true;\n    // logic might be complex\n    println!(\"Doing something...\");\n    result\n}".to_string(),
                        start_line: 10,
                        end_line: 15,
                    },
                    CodeChunk {
                        path: "src/lib.rs".to_string(),
                        snippet: 
                        "fn another_function() -> i32 {\n    // another complex function\n    let value = 42;\n    // more logic here\n    println!(\"Calculating...\");\n    value\n}".to_string(),
                        start_line: 20,
                        end_line: 25,
                    },
                ],
            },
        ];

        let expected_output = "#### PATHS ####\n\
                               repo1:src/lib.rs\n\
                               #### CODE CHUNKS ####\n\n\
                               ### repo1:src/lib.rs ###\n\
                               10: fn lib_function() -> bool {\n\
                               11:     // starts doing something\n\
                               12:     let result = true;\n\
                               13:     // logic might be complex\n\
                               14:     println!(\"Doing something...\");\n\
                               15:     result\n\
                               16: }\n\n\
                               ### repo1:src/lib.rs ###\n\
                               20: fn another_function() -> i32 {\n\
                               21:     // another complex function\n\
                               22:     let value = 42;\n\
                               23:     // more logic here\n\
                               24:     println!(\"Calculating...\");\n\
                               25:     value\n\
                               26: }\n\n";

        let result = generate_llm_context(code_snippets, context_files).unwrap();
        assert_eq!(result, expected_output);
    }
}
