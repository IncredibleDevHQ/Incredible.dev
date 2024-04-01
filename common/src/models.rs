use crate::llm_gateway::api::Message;
use crate::{CodeUnderstandings, CodeContext};
use serde::{de, Deserialize, Deserializer, Serialize};
use std::fmt;
use std::ops::Range;


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

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct TaskList {
    #[serde(skip_serializing_if = "is_empty_task_vec")]
    pub tasks: Option<Vec<Task>>,

    // Use a custom function for checking empty or None String
    #[serde(skip_serializing_if = "is_none_or_empty")]
    pub ask_user: Option<String>,
}

// Custom function to check if the task vector is empty
fn is_empty_task_vec(vec: &Option<Vec<Task>>) -> bool {
    match vec {
        Some(v) => v.is_empty(),
        None => true,
    }
}

// Custom function to check if the string is empty or None
fn is_none_or_empty(str: &Option<String>) -> bool {
    match str {
        Some(s) => s.is_empty(),
        None => true,
    }
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct TaskListResponseWithMessage {
    pub task_list: TaskList,
    pub messages: Vec<Message>,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct Task {
    pub task: String,
    pub subtasks: Vec<Subtask>,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct Subtask {
    pub subtask: String,
    pub questions: Vec<String>,
}

impl fmt::Display for TaskList {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        for (i, task) in self.tasks.iter().enumerate() {
            writeln!(f, "Task {:?}: {:?}", i + 1, task)?;
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


#[derive(Debug, Clone)]
pub struct TasksQuestionsAnswersDetails {
    pub root_node_id: usize,
    pub tasks: Vec<TaskDetailsWithContext>,
}

#[derive(Debug, Clone)]
pub struct AnswerAndContexts {
    pub questions: Vec<String>,
    pub answers: Vec<String>,
    pub code_contexts: Vec<CodeContext>,
    pub merged_code_contexts: Vec<CodeContext>, // Stores the merged contexts
}
#[derive(Debug, Clone)]
pub struct TaskDetailsWithContext {
    pub task_id: usize,
    pub task_description: String,
    pub details: Vec<AnswerAndContexts>,
}

impl fmt::Display for AnswerAndContexts {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "Questions:\n")?;
        for question in &self.questions {
            writeln!(f, "- {}", question)?;
        }

        write!(f, "Answers:\n")?;
        for answer in &self.answers {
            writeln!(f, "- {}", answer)?;
        }

        write!(f, "Merged Code Contexts:\n")?;
        for context in &self.merged_code_contexts {
            writeln!(
                f,
                "- Path: {}\n  Hidden: {}\n  Repo: {}\n  Branch: {:?}\n  Ranges: {:?}\n",
                context.path, context.hidden, context.repo, context.branch, context.ranges
            )?;
        }

        Ok(())
    }
}

impl fmt::Display for TaskDetailsWithContext {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        writeln!(
            f,
            "Task ID: {}\nTask Description: {}\n",
            self.task_id, self.task_description
        )?;
        for (i, detail) in self.details.iter().enumerate() {
            writeln!(f, "Detail {}:\n{}", i + 1, detail)?;
        }

        Ok(())
    }
}

impl fmt::Display for TasksQuestionsAnswersDetails {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        writeln!(f, "Root Node ID: {}\n", self.root_node_id)?;
        for (i, task) in self.tasks.iter().enumerate() {
            writeln!(f, "Task {}:\n{}", i + 1, task)?;
        }

        Ok(())
    }
}
