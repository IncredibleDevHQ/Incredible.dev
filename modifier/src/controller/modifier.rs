use crate::{models::CodeModifierRequest, AppState};
use common::{service_interaction::fetch_code_span, CodeChunk, CodeSpanRequest};
use futures::future::try_join_all;
use std::{collections::HashMap, convert::Infallible, error::Error, sync::Arc};

#[derive(serde::Serialize, serde::Deserialize, Clone, Debug, PartialEq)]
struct CodeSnippets {
    path: String,
    repo: String,
    code_chunks: Vec<CodeChunk>,
}

pub async fn handle_modify_code(
    request: CodeModifierRequest,
    app_state: Arc<AppState>,
) -> Result<impl warp::Reply, Infallible> {
    // Logic to process code modification request

    Ok(warp::reply())
}

async fn get_code_snippets(
    request: CodeModifierRequest,
    code_search_url: String,
) -> Result<Vec<CodeSnippets>, Box<dyn Error>> {
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
                fetch_code_span(url, code_span_request)
                    .await
                    .map(|chunks| (repo_clone, chunks))
            }
        })
        .collect();

    let results = try_join_all(futures).await?;

    aggregate_code_chunks(results)
}

fn aggregate_code_chunks(
    results: Vec<(String, Vec<CodeChunk>)>,
) -> Result<Vec<CodeSnippets>, Box<dyn Error>> {
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
}
