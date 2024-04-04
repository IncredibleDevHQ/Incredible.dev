use std::fmt;
use std::ops::Range;

pub mod ast;
pub mod hasher;
pub mod llm_gateway;
pub mod models;
pub mod prompts;
pub mod service_interaction;
pub mod task_graph;
pub mod config;

pub mod prompt_string_generator {
    use std::future::Future;
    use std::pin::Pin;

    pub trait GeneratePromptString {
        // Return a boxed future. This method will be implemented to generate a prompt.
        // The generic RequestData allows flexibility in what data is required to generate the prompt.
        fn generate_prompt(
            &self,
            url: String,
        ) -> Pin<Box<dyn Future<Output = Result<String, Box<dyn std::error::Error + Send>>> + Send>>;
    }
}

#[derive(serde::Serialize, serde::Deserialize, Clone, Debug, PartialEq)]
pub struct CodeContext {
    pub path: String,
    pub hidden: bool,
    pub repo: String, // Ensure RepoRef is accessible or defined here.
    pub branch: Option<String>,
    pub ranges: Vec<Range<usize>>,
}

#[derive(serde::Serialize, serde::Deserialize, Clone, Debug, PartialEq)]
pub struct CodeUnderstanding {
    pub context: Vec<CodeContext>,
    pub question: String,
    pub answer: String,
}

impl fmt::Display for CodeUnderstanding {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "Question: {}\nAnswer: {}\n", self.question, self.answer)?;
        for (i, context) in self.context.iter().enumerate() {
            write!(f, "Context {}:\n", i + 1)?;
            write!(f, "\tPath: {}\n", context.path)?;
            write!(f, "\tRepository: {}\n", context.repo)?;
            if let Some(branch) = &context.branch {
                write!(f, "\tBranch: {}\n", branch)?;
            }
            write!(f, "\tHidden: {}\n", context.hidden)?;
            write!(f, "\tRanges: {:?}\n", context.ranges)?;
        }
        Ok(())
    }
}

#[derive(serde::Serialize, serde::Deserialize, Clone, Debug, PartialEq, Default)]
pub struct CodeUnderstandings {
    pub repo: String,
    pub issue_description: String,
    pub qna: Vec<CodeUnderstanding>,
}

// Represents a code chunk
#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct CodeChunk {
    pub path: String,
    #[serde(rename = "snippet")]
    pub snippet: String,
    #[serde(rename = "start")]
    pub start_line: usize,
    #[serde(rename = "end")]
    pub end_line: usize,
}

impl std::fmt::Display for CodeChunk {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let lines: Vec<&str> = self.snippet.lines().collect();
        for (i, line) in lines.iter().enumerate() {
            // Calculate the line number starting from start_line
            let line_number = i + self.start_line;
            writeln!(f, "{}: {}", line_number, line)?;
        }

        Ok(())
    }
}

#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct TokenInfoRequest {
    #[serde(rename = "repo_name")]
    pub repo_ref: String,
    #[serde(rename = "file_path")]
    pub relative_path: String,
    pub branch: Option<String>,
    pub start: usize,
    pub end: usize,
}
