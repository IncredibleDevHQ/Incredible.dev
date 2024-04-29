use std::{convert::Infallible, mem, ops::Not, sync::Arc};

use anyhow::{anyhow, Result};
use common::{
    ast::{
        ast_graph::NodeKind,
        graph_code_pluck::ContentDocument,
        language_support::{Language, TSLanguage},
        text_range::TextRange,
    },
    hasher::generate_quikwit_index_name,
    TokenInfoRequest,
};
use compact_str::CompactString;
use reqwest::StatusCode;
use smallvec::SmallVec;

use crate::{
    code_navigation::{CodeNavigationContext, FileSymbols, Occurrence, OccurrenceKind, Token}, config::AppState, search::{
        code_search::get_file_content,
        quikwit::{get_all_files_for_repo, search_quickwit},
    }, snippet::Snipper
};

pub async fn handle_token_info_fetcher_wrapper(
    request: TokenInfoRequest,
    app_state: Arc<AppState>,
) -> anyhow::Result<impl warp::Reply, Infallible> {
    match handle_token_info_fetcher(request, app_state).await {
        Ok(response) => Ok(warp::reply::with_status(
            warp::reply::json(&response),
            StatusCode::OK,
        )),
        Err(e) => {
            log::error!("Error processing modify code request: {}", e);
            // TODO: Convert the error message into a structured error response
            let error_message = format!("Error processing request: {}", e);
            Ok(warp::reply::with_status(
                warp::reply::json(&error_message),
                StatusCode::INTERNAL_SERVER_ERROR,
            ))
        }
    }
}

async fn handle_token_info_fetcher(
    request: TokenInfoRequest,
    app_state: Arc<AppState>,
) -> Result<Vec<FileSymbols>, anyhow::Error> {
    let source_document = match get_file_content(
        &request.relative_path.clone(),
        &request.repo_ref.clone(),
        app_state.clone(),
    )
    .await
    {
        Ok(Some(doc)) => doc,
        Ok(None) => return Err(anyhow!("No document found")),
        Err(e) => {
            return Err(anyhow::Error::from(e));
        }
    };

    let all_docs = match get_all_files_for_repo(
        &generate_quikwit_index_name(&request.repo_ref.clone()),
        &request.repo_ref.clone(),
    )
    .await
    {
        Ok(docs) => docs,
        Err(e) => {
            return Err(anyhow!("Failed to fetch all files: {}", e));
        }
    };

    match get_token_info(
        request.clone(),
        request.repo_ref.clone(),
        &source_document,
        &all_docs,
        Some(0),
        Some(0),
        app_state,
    )
    .await
    {
        Ok(content) => {
            log::debug!(
                "Token info fetched successfully: {}",
                serde_json::to_string(&content)?
            );
            return Ok(content);
        }
        Err(e) => return Err(anyhow::anyhow!("failed to fetch source content: {}", e)),
    }
}

pub async fn get_token_info(
    params: TokenInfoRequest,
    repo_ref: String,
    source_doc: &ContentDocument,
    all_docs: &Vec<ContentDocument>,
    context_before: Option<usize>, // This will be None
    context_after: Option<usize>,  // This will be None
    app_state: Arc<AppState>,
) -> anyhow::Result<Vec<FileSymbols>> {
    let source_document_idx = all_docs
        .iter()
        .position(|doc| doc.relative_path == source_doc.relative_path)
        .ok_or(anyhow::anyhow!("invalid language"))?;

    let snipper =
        Some(Snipper::default().context(context_before.unwrap_or(0), context_after.unwrap_or(0)));

    let ctx: CodeNavigationContext<'_, '_> = CodeNavigationContext {
        token: Token {
            repo: repo_ref.clone(),
            relative_path: params.relative_path.as_str(),
            start_byte: params.start,
            end_byte: params.end,
        },
        all_docs,
        source_document_idx,
        snipper,
    };

    let data = ctx.token_info();
    if data.is_empty() {
        search_nav(
            repo_ref.clone(),
            ctx.active_token_text(),
            ctx.active_token_range(),
            params.branch.as_deref(),
            source_doc,
            snipper,
            app_state,
        )
        .await
    } else {
        Ok(data)
    }
}

async fn search_nav(
    repo_ref: String,
    hovered_text: &str,
    payload_range: std::ops::Range<usize>,
    branch: Option<&str>,
    source_document: &ContentDocument,
    snipper: Option<Snipper>,
    app_state: Arc<AppState>,
) -> anyhow::Result<Vec<FileSymbols>> {
    let associated_langs = match source_document.lang.as_deref().map(TSLanguage::from_id) {
        Some(Language::Supported(config)) => config.language_ids,
        _ => &[],
    };

    // produce search based results here
    let regex_str = regex::escape(hovered_text);
    let target = regex::Regex::new(&format!(r"\b{regex_str}\b")).expect("failed to build regex");
    // perform a text search for hovered_text
    let query = build_quickwit_query(
        &repo_ref,
        hovered_text,
        branch.map(|b| vec![b]),
        associated_langs.to_vec(),
    );
    let results = match search_quickwit(&repo_ref, &query).await {
        Ok(results) => results,
        Err(e) => {
            return Err(anyhow!("Failed to search quickwit: {}", e));
        }
    };

    // if the hovered token is a def, ignore all other search-based defs
    let ignore_defs = match source_document.symbol_locations() {
        Ok(symbol_locations) => symbol_locations
            .scope_graph()
            .and_then(|graph| {
                graph
                    .node_by_range(payload_range.start, payload_range.end)
                    .map(|idx| matches!(graph.graph[idx], NodeKind::Def(_)))
            })
            .unwrap_or_default(),
        Err(_e) => false, // Might make sense to return an error here.
    };

    let data = results
        .into_iter()
        .filter_map(|doc| {
            let hoverable_ranges = doc.hoverable_ranges()?;
            let line_end_indices_u32: Vec<u32> = doc
                .line_end_indices
                .iter()
                .map(|&byte| byte as u32)
                .collect();
            let data = target
                .find_iter(&doc.content)
                .map(|m| TextRange::from_byte_range(m.range(), &line_end_indices_u32))
                .filter(|range| hoverable_ranges.iter().any(|r| r.contains(range)))
                .filter(|range| {
                    !(payload_range.start >= range.start.byte
                        && payload_range.end <= range.end.byte)
                })
                .map(|range| {
                    let start_byte = range.start.byte;
                    let end_byte = range.end.byte;
                    let is_def = match doc.symbol_locations() {
                        Ok(symbol_locations) => symbol_locations
                            .scope_graph()
                            .and_then(|graph| {
                                graph
                                    .node_by_range(start_byte, end_byte)
                                    .map(|idx| matches!(graph.graph[idx], NodeKind::Def(_)))
                            })
                            .map(|d| {
                                if d {
                                    OccurrenceKind::Definition
                                } else {
                                    OccurrenceKind::Reference
                                }
                            })
                            .unwrap_or_default(),
                        Err(_) => OccurrenceKind::Reference, // Might be better to just log and move on instead of going assuming it's a ref
                    };
                    let highlight = start_byte..end_byte;
                    let snippet = snipper
                        .unwrap_or_default()
                        .expand(highlight, &doc.content, &doc.line_end_indices)
                        .reify(&doc.content, &[]);

                    Occurrence {
                        kind: is_def,
                        range,
                        snippet,
                    }
                })
                .filter(|o| !(ignore_defs && o.is_definition())) // if ignore_defs is true & o is a def, omit it
                .collect::<Vec<_>>();

            let file = doc.relative_path;

            data.is_empty().not().then(|| FileSymbols {
                file: file.clone(),
                repo: repo_ref.clone(),
                data,
            })
        })
        .collect::<Vec<_>>();

    Ok(data)
}

pub fn build_quickwit_query(
    repo_ref: &str,
    hovered_text: &str,
    branches: Option<Vec<&str>>,
    associated_langs: Vec<&str>,
) -> String {
    let repo_ref_query = format!("repo_ref:{}", repo_ref);
    let content_query = trigrams(hovered_text)
        .map(|trigram| format!("content:{}", trigram))
        .collect::<Vec<_>>()
        .join(" OR ");

    #[allow(unused)] // TODO: Remove this once branch queries are supported
    let branch_queries = match branches {
        Some(brs) => brs
            .iter()
            .flat_map(|branch| trigrams(branch))
            .map(|trigram| format!("branches:{}", trigram))
            .collect::<Vec<_>>()
            .join(" OR "),
        None => String::new(),
    };

    let lang_queries = associated_langs
        .iter()
        .map(|lang| format!("lang:{}", lang))
        .collect::<Vec<_>>()
        .join(" OR ");

    let query_parts = vec![
        repo_ref_query,
        format!("({})", content_query),
        format!("({})", lang_queries),
    ];

    // TODO: Uncomment this when we start saving branch information in Quickwit
    // if !branch_queries.is_empty() {
    //     query_parts.insert(2, format!("({})", branch_queries));
    // }

    format!("({})", query_parts.join(" AND "))
}

pub fn trigrams(s: &str) -> impl Iterator<Item = CompactString> {
    let mut chars = s.chars().collect::<SmallVec<[char; 6]>>();

    std::iter::from_fn(move || match chars.len() {
        0 => None,
        1..=3 => Some(mem::take(&mut chars).into_iter().collect()),
        _ => {
            let out = chars.iter().take(3).collect();
            chars.remove(0);
            Some(out)
        }
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_build_quickwit_query_with_branch() {
        let repo_ref = "aider";
        let hovered_text = "scrub_sensitive_info";
        let branches = Some(vec!["main"]);
        let associated_langs = vec!["Python"];

        let query = build_quickwit_query(repo_ref, hovered_text, branches, associated_langs);

        let expected_query = "(repo_ref:aider AND (content:scr OR content:cru OR content:rub OR content:ub_ OR content:b_s OR content:_se OR content:sen OR content:ens OR content:nsi OR content:sit OR content:iti OR content:tiv OR content:ive OR content:ve_ OR content:e_i OR content:_in OR content:inf OR content:nfo) AND (lang:Python))";
        assert_eq!(
            query, expected_query,
            "The generated Quickwit query does not match the expected output."
        );
    }
}
