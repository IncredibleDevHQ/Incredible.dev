use std::ops::Range;
use serde::{Serialize, Deserialize};
use crate::CodeUnderstandings;
use std::fmt;

#[derive(serde::Serialize, serde::Deserialize, Clone, Debug, PartialEq)]
pub struct GenerateQuestionRequest {
    pub issue_desc: String,
    pub repo_name: String,
}

/// Represents a code chunk
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
            writeln!(f, "{:4} {}", i + self.start_line, line)?;
        }
        Ok(())
    }
}
// Used to get code chunks given the repo, branch, path, range and id.
#[derive(serde::Serialize, serde::Deserialize, Clone, Debug, PartialEq)]
pub struct CodeSpanRequest {
    pub repo: String,
    pub branch: Option<String>,
    pub path: String,
    // text range of the code chunk from the file to extract
    pub ranges: Option<Vec<Range<usize>>>,
    pub id: Option<String>,
}

#[derive(serde::Serialize, serde::Deserialize, Clone, Debug, PartialEq)]
pub struct CodeUnderstandRequest {
    pub query: String,
    pub repo: String,
}

#[derive(serde::Serialize, serde::Deserialize, Clone, Debug, PartialEq)]
pub struct CodeContextRequest {
    // Contains the detailed code understandings and issue description to be processed.
    pub qna_context: CodeUnderstandings,
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
