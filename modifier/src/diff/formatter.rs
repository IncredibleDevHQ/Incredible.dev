use std::fmt::{self};

use super::diff::DiffChunk;
use anyhow::{Context, Result};

#[derive(serde::Serialize, serde::Deserialize)]
pub struct Diff {
    pub chunks: Vec<Chunk>,
}

impl fmt::Display for Diff {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        use std::fmt::Write;

        let mut s = String::new();

        for c in &self.chunks {
            writeln!(s, "--- {}\n+++ {}", c.file, c.file)?;

            for h in &c.hunks {
                writeln!(s, "@@ -{},0 +{},0 @@", h.line_start, h.line_start)?;
                write!(s, "{}", h.patch)?;
            }
        }

        for c in super::diff::relaxed_parse(&s) {
            write!(f, "{}", c)?;
        }

        Ok(())
    }
}

#[derive(serde::Serialize, serde::Deserialize)]
pub struct Chunk {
    pub file: String,
    pub repo: String,
    pub branch: Option<String>,
    pub lang: Option<String>,
    pub hunks: Vec<Hunk>,
    pub raw_patch: String,
}

#[derive(serde::Serialize, serde::Deserialize)]
pub struct Hunk {
    pub line_start: usize,
    pub patch: String,
}

pub fn format_diffs(chunks: Vec<DiffChunk>) -> Result<Diff, anyhow::Error> {
    let mut diff = Diff { chunks: vec![] };

    for chunk in chunks {
        let path = chunk.src.as_deref().or(chunk.dst.as_deref()).unwrap();
        let (repo, path) = parse_diff_path(path)?;

        let mut hunks = vec![];

        for hunk in chunk.hunks.clone() {
            hunks.push(Hunk {
                line_start: hunk.src_line,
                patch: hunk
                    .lines
                    .into_iter()
                    .map(|line| line.to_string())
                    .collect::<String>(),
            });
        }

        diff.chunks.push(Chunk {
            file: path.to_owned(),
            repo: repo.to_owned(),
            branch: None, // Take this from parent
            lang: None,
            hunks,
            raw_patch: chunk.clone().to_string(),
        });
    }

    Ok(diff)
}

fn parse_diff_path(p: &str) -> Result<(&str, &str), anyhow::Error> {
    let (repo, path) = p
        .split_once(':')
        .context("diff path did not conform to repo:path syntax")?;

    Ok((repo, path))
}
