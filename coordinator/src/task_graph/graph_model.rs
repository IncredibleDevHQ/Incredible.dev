use common::llm_gateway::api::{Message, MessageSource};
use petgraph::graph::{DiGraph, NodeIndex};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

extern crate common;
use common::{CodeContext, CodeUnderstanding};

/// Represents the process of tracking tasks, subtasks, and questions within a directed graph.
/// Each instance of `TrackProcess` maintains its own graph, root node, and unique identifier (UUID)
#[derive(Serialize, Deserialize, Debug)]
pub struct TrackProcessV1 {
    pub repo: String,
    pub graph: DiGraph<NodeV1, EdgeV1>, // The directed graph holding the nodes (tasks, subtasks, questions) and edges.
    pub last_added_node: Option<NodeIndex>,
    pub root_node: NodeIndex, // Index of the root node in the graph, representing the primary issue or task.
    pub uuid: Uuid, // Unique identifier for the root node (and implicitly, the tracking process).
}

impl TrackProcessV1 {
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
        let mut graph = DiGraph::<NodeV1, EdgeV1>::new(); // Create a new, empty directed graph.
        let uuid = Uuid::new_v4(); // Generate a new UUID for the root node.
        let root_node_index = graph.add_node(NodeV1::Conversation(
            MessageSource::User,
            Message::system(root_issue),
            uuid,
        ));

        // Return the new `TrackProcess` instance containing the graph, root node index, and UUID.
        TrackProcessV1 {
            repo: repo.to_string(),
            graph,
            last_added_node: Some(root_node_index),
            root_node: root_node_index,
            uuid,
        }
    }
}

/// Defines the types of nodes that can exist within the task tracking graph.
#[derive(Debug, serde::Serialize, serde::Deserialize)]
pub enum NodeV1 {
    // Represents a conversation node with a message source.
    // Message source is a enum that represents either an assistant, system or user message.
    // Message is a struct that contains the message text in the json form with which we send conversation history to the LLM
    // Uuid is the unique identifier for the duration of the entire conversation
    // this is to help identify the first conversation in the conversation history.
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
