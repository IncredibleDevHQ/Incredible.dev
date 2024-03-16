use std::ops::Range;
use std::fmt;
use serde::{Serialize, Deserialize};

pub mod hasher;
pub mod llm_gateway;
pub mod models;
pub mod service_interaction;

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

// types for parsing the breakdown of task into subtasks and their corresponding questions 
#[derive(Serialize, Deserialize, Debug)]
pub struct TaskList {
    pub tasks: Vec<Task>,
}

#[derive(Serialize, Deserialize, Debug)]
pub struct Task {
    pub task: String,
    pub subtasks: Vec<Subtask>,
}

#[derive(Serialize, Deserialize, Debug)]
pub struct Subtask {
    pub subtask: String,
    pub questions: Vec<String>,
}


impl fmt::Display for TaskList {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        for (i, task) in self.tasks.iter().enumerate() {
            writeln!(f, "Task {}: {}", i + 1, task)?;
        }
        Ok(())
    }
}

impl fmt::Display for Task {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        writeln!(f, "{}", self.task)?;
        for (i, subtask) in self.subtasks.iter().enumerate() {
            writeln!(f, "  Subtask {}: {}", i + 1, subtask)?;
        }
        Ok(())
    }
}

impl fmt::Display for Subtask {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        writeln!(f, "{}", self.subtask)?;
        for (i, question) in self.questions.iter().enumerate() {
            writeln!(f, "    Question {}: {}", i + 1, question)?;
        }
        Ok(())
    }
}
