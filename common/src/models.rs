use ai_gateway::message::message::Message; 
use crate::{CodeContext, CodeUnderstandings};
use serde::{de, Deserialize, Serialize};
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
    pub task_id: String,
    pub question_id: usize, 
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
    // summary of all the questions answers for the tasks. Here is a sample summary:
    // - User Query: The user wants the application to make calls to the code-understanding service API, and for each question received in the response, it needs to call another API from the code-understanding service for the answers.
    // - Task 1 involves modifying the API inside the coordinator service to call the code-understanding service API.
    //     - The code-understanding service API receives and processes incoming data using `warp` and `serde` libraries.
    //     - The coordinator service API passes data to the code-understanding service API via POST requests.
    //     - To connect to the code-understanding API service, client configuration is needed, which includes setting up the base URL, HTTP client, model, and bearer token (if needed).
    //     - The actual connection with the code-understanding service isn't established in Coordinator service itself, but the URL to the code-understanding service is provided as an environment variable named `CODE_UNDERSTANDING_URL`.
    //     - The coordinator service API doesn't call any other services directly, but there is evidence of calling other services in the `modifier` microservice.
    //     - The Coordinator service API in this context is a simple HTTP web service with a home endpoint and a suggest endpoint for suggestion related operations.
    // - Task 2 involves calling another API from the code-understanding service to obtain answers for each question returned from the code-understanding service API:
    //     - The expected response containing the answers is formatted in the `Exchange` struct.
    //     - The code-understanding API expect queries in a particular structure as a part of requests made to it.
    //     - The specified API endpoint doesn't exist in this codebase for obtaining answers, but it's apparent that `https://api.openai.com/v1/chat/completions` endpoint from the OpenAI API is used to simulate conversations which might involve roughly the same functionality.
    //     - Answer within questions possibly refer to various structs, enums, and types defined in code snippets.
    //     - Questions within the response are structured in a JSON array in string format, containing different phrasing of same underlying problem.
    //     - The response from the code-understanding service API is in a form of `ChatCompletion` struct.
    
    // Questions to present to the senior software engineer:
    
    // 1. Which API endpoint should be used to obtain answers from the code-understanding service API? Is it within the given codebase or is an external API involved (like OpenAI)?
    // 2. How are the connections between coordinator service API and the code-understanding service API established?
    // 3. What is the actual operation performed by `handle_modify_code_wrapper` function in the `perform_suggest` method of the coordinator service API?
    // 4. Are there any authentication requirements or details to know about when configuring the client for connection with the code-understanding service API?
    // 5. Are there any limitations or constraints to consider when interacting with these APIs?
    pub answer_summary: Option<String>,
}

#[derive(Debug, Clone)]
pub struct TaskDetailsWithContext {
    // Task ID is derive from the node index in the graph.
    pub task_id: usize,
    pub task_description: String,
    pub questions: Vec<String>,
    pub answers: Vec<String>,
    pub code_contexts: Vec<CodeContext>,
    pub merged_code_contexts: Vec<CodeContext>,
}

impl fmt::Display for TaskDetailsWithContext {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        write!(
            f,
            "Task ID: {}\nTask Description: {}\n",
            self.task_id, self.task_description
        )?;

        write!(f, "Questions:\n")?;
        for question in &self.questions {
            write!(f, " - {}\n", question)?;
        }

        write!(f, "Answers:\n")?;
        for answer in &self.answers {
            write!(f, " - {}\n", answer)?;
        }

        write!(f, "Code Contexts:\n")?;
        for context in &self.merged_code_contexts {
            write!(f, " - {:?}\n", context)?;
        }

        Ok(())
    }
}

impl fmt::Display for TasksQuestionsAnswersDetails {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        write!(f, "Root Node ID: {}\n", self.root_node_id)?;
        for (i, task) in self.tasks.iter().enumerate() {
            write!(f, "Task {}:\n{}\n", i + 1, task)?;
        }
        Ok(())
    }
}
