use petgraph::graph::{DiGraph, NodeIndex};
use uuid::Uuid;
use serde::{Serialize, Deserialize};

extern crate common;
use common::models::{TaskList};
use common::CodeContext;

/// Represents the process of tracking tasks, subtasks, and questions within a directed graph.
/// Each instance of `TrackProcess` maintains its own graph, root node, and unique identifier (UUID).
pub struct TrackProcess {
    pub repo: String,
    pub graph: DiGraph<Node, Edge>,  // The directed graph holding the nodes (tasks, subtasks, questions) and edges.
    pub root_node: NodeIndex,        // Index of the root node in the graph, representing the primary issue or task.
    pub uuid: Uuid,                  // Unique identifier for the root node (and implicitly, the tracking process).
    pub question_counter: usize,     // Counter to keep track of the number of questions generated.
}

impl TrackProcess {
    /// Constructs a new `TrackProcess` with a specified root issue.
    /// 
    /// # Arguments
    /// 
    /// * `root_issue` - A string slice representing the description of the root issue or main task.
    /// 
    /// # Returns
    /// 
    /// A new `TrackProcess` instance with the root node initialized and added to its graph.
    pub fn new(repo: &str, root_issue: &str) -> Self {
        let mut graph = DiGraph::<Node, Edge>::new();  // Create a new, empty directed graph.
        let uuid = Uuid::new_v4();  // Generate a new UUID for the root node.
        // Create the root node with the issue description, UUID, and initial status, then add it to the graph.
        let root_node_index = graph.add_node(Node::RootIssue(root_issue.to_string(), uuid, ChildTaskStatus::NotStarted));

        // Return the new `TrackProcess` instance containing the graph, root node index, and UUID.
        TrackProcess {
            repo: repo.to_string(),
            graph,
            root_node: root_node_index,
            uuid,
            question_counter: 0,  // Initialize the counter to zero.
        }
    }
}

/// Defines the types of nodes that can exist within the task tracking graph.
#[derive(Debug)]
pub enum Node {
    RootIssue(String, Uuid, ChildTaskStatus),  // Represents the initial issue or task with a status and UUID.
    Task(String),                              // Represents a discrete task derived from the root issue.
    Subtask(String),                           // Represents a subtask under a specific task.
    Question(usize, String, ChildTaskStatus),                       // Represents a question related to a specific subtask.
    Answer(String),          // Represents an answer to a question.
    CodeContext(CodeContext),  // Represents a code context associated with an answer.
}

/// Defines the types of edges to represent relationships between nodes in the task tracking graph.
#[derive(Debug)]
pub enum Edge {
    Task,        // An edge from a root issue or task to a specific task.
    Subtask,     // An edge from a task to a specific subtask.
    Question,    // An edge from a subtask to a question about that subtask.
    Answer,         // Connects a question to its answer.
    CodeContext,    // Connects an answer to its code context.
}

/// Represents the possible statuses of the root issue's child elements (tasks, subtasks).
#[derive(Debug)]
pub enum ChildTaskStatus {
    NotStarted,  // Indicates that the task or subtask has not yet been started.
    InProgress,  // Indicates that the task or subtask is currently in progress.
    Done,        // Indicates that the task or subtask has been completed.
}

impl Default for ChildTaskStatus {
    fn default() -> Self {
        ChildTaskStatus::NotStarted
    }
}

// Define a struct to hold questions along with their IDs.
pub struct QuestionWithId {
    pub id: usize,
    pub text: String,
}

// implement Display for QuestionWithId
impl std::fmt::Display for QuestionWithId {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "Question {}: {}", self.id, self.text)
    }
}