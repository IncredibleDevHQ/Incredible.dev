use crate::{agent::prompts, utils::llm_gateway, CONFIG};
use anyhow::{anyhow, Context, Result};
use common::{service_interaction::fetch_code_span, CodeChunk, models::CodeSpanRequest};

use futures::{StreamExt, TryStreamExt};

use super::diff::{self, DiffChunk, DiffHunk};

pub async fn validate_diffs(
    diff_response: &str,
    llm_context: String,
    llm_gateway: llm_gateway::Client,
) -> Result<Vec<DiffChunk>, anyhow::Error> {
    // Extract diff chunks, handle error immediately if extraction fails.
    let diff_chunks = match diff::extract(diff_response) {
        Ok(diff_chunks_iter) => diff_chunks_iter.collect::<Vec<_>>(),
        Err(e) => {
            log::error!("Error extracting diff chunks: {:?}", e);
            return Err(anyhow!("Error extracting diff chunks: {:?}", e));
        }
    };

    let valid_chunks = futures::stream::iter(diff_chunks)
        .map(|mut chunk| {
            let llm_context = llm_context.clone();
            let llm_gateway = llm_gateway.clone();

            async move {
                match (&chunk.src, &chunk.dst) {
                    (Some(src), Some(dst)) => {
                        if src != dst {
                            log::error!(
                                "patch source and destination file were different: \
                                got `{src}` and `{dst}`"
                            );

                            return Ok(None);
                        }

                        let (repo, path) = diff::parse_diff_path(src)?;

                        chunk.hunks = rectify_hunks(
                            &llm_context,
                            &llm_gateway,
                            chunk.hunks.iter(),
                            path,
                            &repo,
                            None,
                        )
                        .await?;

                        Ok(Some(chunk))
                    }

                    (Some(src), None) => {
                        let (repo, path) = diff::parse_diff_path(src)?;
                        if validate_delete_file(path, &repo, None).await? {
                            Ok(Some(chunk))
                        } else {
                            Ok(None)
                        }
                    }

                    (None, Some(dst)) => {
                        let (repo, path) = diff::parse_diff_path(dst)?;
                        if validate_add_file(&chunk, path, &repo, None).await? {
                            Ok(Some(chunk))
                        } else {
                            Ok(None)
                        }
                    }

                    (None, None) => {
                        log::error!("patch chunk had no file source or destination");
                        Ok(None)
                    }
                }
            }
        })
        .buffered(10)
        .try_filter_map(|c: Option<_>| async move { Ok::<_, anyhow::Error>(c) })
        .try_collect::<Vec<_>>()
        .await
        .context("failed to interpret diff chunks")?;

    Ok(valid_chunks)
}

async fn rectify_hunks(
    llm_context: &str,
    llm_gateway: &llm_gateway::Client,
    hunks: impl Iterator<Item = &DiffHunk>,
    path: &str,
    repo: &str,
    branch: Option<&str>,
) -> Result<Vec<DiffHunk>> {
    let file_chunks = get_file_content(path, repo, branch).await?;

    if file_chunks.is_empty() {
        log::error!("diff tried to modify a file that doesn't exist: {path}");
        return Ok(Vec::new());
    }

    let mut file_content = file_chunks.first().unwrap().snippet.clone();

    let mut out = Vec::new();

    for (i, hunk) in hunks.enumerate() {
        let mut singular_chunk = DiffChunk {
            src: Some(path.to_owned()),
            dst: Some(path.to_owned()),
            hunks: vec![hunk.clone()],
        };

        let diff = singular_chunk.to_string();
        let patch = diffy::Patch::from_str(&diff).context("invalid patch")?;

        if let Ok(t) = diffy::apply(&file_content, &patch) {
            file_content = t;
            out.extend(singular_chunk.hunks);
        } else {
            log::debug!("fixing up patch:\n\n{hunk:?}\n\n{diff}");

            singular_chunk.hunks[0].lines.retain(|line| match line {
                diff::Line::AddLine(..) | diff::Line::DelLine(..) => true,
                diff::Line::Context(..) => false,
            });
            singular_chunk.fixup_hunks();

            let diff = if singular_chunk.hunks[0]
                .lines
                .iter()
                .all(|l| matches!(l, diff::Line::AddLine(..)))
            {
                let system_prompt = prompts::studio_diff_regen_hunk_prompt(llm_context);
                let messages = vec![
                    llm_gateway::api::Message::system(&system_prompt),
                    llm_gateway::api::Message::user(&singular_chunk.to_string()),
                ];

                let llm_response = llm_gateway.chat(&messages, None).await?;
                llm_response.choices[0]
                    .message
                    .content
                    .clone()
                    .unwrap_or_else(|| String::new())
            } else {
                singular_chunk.to_string()
            };

            let patch = diffy::Patch::from_str(&diff).context("redacted patch was invalid")?;

            if let Ok(t) = diffy::apply(&file_content, &patch) {
                file_content = t;
                out.extend(singular_chunk.hunks);
            } else {
                log::warn!("hunk {path}#{i} failed: {diff}");
            }
        }
    }

    Ok(out)
}

async fn validate_delete_file(path: &str, repo: &str, branch: Option<&str>) -> Result<bool> {
    if get_file_content(path, repo, branch).await?.is_empty() {
        log::error!("diff tried to delete a file that doesn't exist: {path}");
        Ok(false)
    } else {
        Ok(true)
    }
}

async fn validate_add_file(
    chunk: &DiffChunk,
    path: &str,
    repo: &str,
    branch: Option<&str>,
) -> Result<bool> {
    if !get_file_content(path, repo, branch).await?.is_empty() {
        log::error!("diff tried to create a file that already exists: {path}");
        return Ok(false);
    };

    if chunk.hunks.iter().any(|h| {
        h.lines
            .iter()
            .any(|l| !matches!(l, diff::Line::AddLine(..)))
    }) {
        log::error!("diff to create a new file had non-addition lines");
        Ok(false)
    } else {
        Ok(true)
    }
}

async fn get_file_content(path: &str, repo: &str, branch: Option<&str>) -> Result<Vec<CodeChunk>> {
    let url = CONFIG.code_search_url.clone();
    let code_span_request = CodeSpanRequest {
        path: path.to_string().clone(),
        branch: branch.map(|s| s.to_string()).clone(),
        repo: repo.to_string().clone(),
        ranges: None,
        id: None,
    };
    match fetch_code_span(url, code_span_request).await {
        Ok(code_chunks) => Ok(code_chunks),
        Err(e) => {
            log::error!("Failed to fetch code span: {}", e);
            Ok(Vec::new())
        }
    }
}
