use common::llm_gateway::api::{Message, MessageSource};
use petgraph::graph::{DiGraph, NodeIndex};
use serde::{Deserialize, Serialize};
use std::time::SystemTime;
use uuid::Uuid;

extern crate common;
use common::{CodeContext, CodeUnderstanding};

/// Represents the process of tracking tasks, subtasks, and questions within a directed graph.
/// Each instance of `TrackProcess` maintains its own graph, root node, and unique identifier (UUID)
#[derive(Serialize, Deserialize, Debug)]
pub struct TrackProcessV1 {
    pub repo: String,
    pub graph: Option<DiGraph<NodeV1, EdgeV1>>,
    pub root_node: Option<NodeIndex>,
    pub last_added_node: Option<NodeIndex>,
    pub last_added_conversation_node: Option<NodeIndex>,
    pub time_created: SystemTime,
    pub last_updated: SystemTime,
}


impl TrackProcessV1 {
    /// Constructs a new `TrackProcessV1` instance.
    pub fn new(repo: &str) -> Self {
        Self {
            repo: repo.to_string(),
            graph: None,
            root_node: None,
            last_added_node: None,
            last_added_conversation_node: None,
            time_created: SystemTime::now(),
            last_updated: SystemTime::now(),
        }
    }
    
    /// Initializes the graph and root node if they do not exist.
    pub fn initialize_graph(&mut self) {
        if self.graph.is_none() {
            let mut graph = DiGraph::new();
            let root_uuid = Uuid::new_v4();
            let root_node = graph.add_node(NodeV1::Root(root_uuid));
            self.graph = Some(graph);
            self.root_node = Some(root_node);
            self.last_added_node = Some(root_node);
            // Update the last added conversation node to root initially.
            self.last_added_conversation_node = Some(root_node);
        }
    }
}

/// Defines the types of nodes that can exist within the task tracking graph.
#[derive(Debug, serde::Serialize, serde::Deserialize)]
pub enum NodeV1 {
    Root(Uuid), // Root node with a UUID to uniquely identify the conversation or session.
    Conversation(MessageSource, Message, Uuid), // Represents a conversation node with a message source.
    Task(String),             // Represents a discrete task derived from the root issue.
    Subtask(String),          // Represents a subtask under a specific task.
    Question(usize, String),  // Represents a question related to a specific subtask.
    Answer(String),           // Represents an answer to a question.
    CodeContext(CodeContext), // Represents a code context associated with an answer.
}

impl NodeV1 {
    /// Checks if the node is a conversation node.
    pub fn is_conversation(&self) -> bool {
        matches!(self, NodeV1::Conversation(..))
    }
}

/// Defines the types of edges to represent relationships between nodes in the task tracking graph.
#[derive(Debug, Serialize, Deserialize)]
pub enum EdgeV1 {
    // This edge connects one Conversation node to the next Conversation node as the chat progresses.
    NextConversation,
    // Process edge connects a Conversation node to the nodes representing the tasks, subtasks, and questions, and other downstream processing data.
    Process,
    Task,        // An edge from a root issue or task to a specific task.
    Subtask,     // An edge from a task to a specific subtask.
    Question,    // An edge from a subtask to a question about that subtask.
    Answer,      // Connects a question to its answer.
    CodeContext, // Connects an answer to its code context.
}

// Define a struct to hold questions along with their IDs.
#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct QuestionWithId {
    pub id: usize,
    pub text: String,
}

// Type to keep the question, their IDs along with answers in the form of CodeUnderstanding type
#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct QuestionWithAnswer {
    pub question_id: usize,
    pub question: String,
    pub answer: CodeUnderstanding,
}

// implement Display for QuestionWithId
impl std::fmt::Display for QuestionWithId {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "Question {}: {}", self.id, self.text)
    }
}
