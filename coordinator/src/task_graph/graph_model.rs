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

    // Initializes the graph and root node if they haven't been already.
    pub fn initialize_graph(&mut self) {
        if self.graph.is_none() {
            let mut new_graph = DiGraph::new();
            let root_node = new_graph.add_node(NodeV1::Root(Uuid::new_v4().to_string()));
            self.graph = Some(new_graph);
            self.root_node = Some(root_node);
            self.time_created = SystemTime::now();
            self.last_updated = self.time_created;
        }
    }
    /// Retrieves the UUID of the root node.
    pub fn get_root_node_uuid(&self) -> Option<String> {
        // Check if the graph and root node are initialized.
        if let Some(ref graph) = self.graph {
            if let Some(root_node) = self.root_node {
                // Get the root node's weight and extract the UUID if it's a Root node.
                if let Some(NodeV1::Root(uuid)) = graph.node_weight(root_node) {
                    return Some(uuid.to_string());
                }
            }
        }

        // Return None if the graph is not initialized or the root node is not of type Root.
        None
    }
}

/// Defines the types of nodes that can exist within the task tracking graph.
#[derive(Debug, serde::Serialize, serde::Deserialize, Clone)]
pub enum NodeV1 {
    Root(String), // Root node with a UUID to uniquely identify the conversation or session.
    Conversation(MessageSource, Message, String), // Represents a conversation node with a message source.
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

#[derive(Debug, Clone)]
pub struct ConversationChain {
    pub user_message: Message,
    pub system_message: Message,
    pub assistant_message: Message,
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
