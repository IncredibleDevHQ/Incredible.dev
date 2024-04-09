use std::error::Error;
use std::fmt;
use std::time::SystemTime;
use uuid::Uuid;

use ai_gateway::message::message::Message; 
use ai_gateway::message::message::MessageRole; 
use crate::task_graph::graph_model::TrackProcessV1;
use crate::task_graph::graph_model::{EdgeV1, NodeV1};
use anyhow::Result;
use petgraph::graph::NodeIndex;

#[derive(Debug)]
pub enum NodeError {
    GraphNotInitialized,
    RootNodeNotFound,
    NodeNotFound(String),
    InvalidNodeId,
    MissingParentNode,
    MissingLastUpdatedNode,
    InvalidQuestionNode,
    NoTaskFound,
    RedisSaveError,
}

impl fmt::Display for NodeError {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        match *self {
            NodeError::GraphNotInitialized => {
                write!(f, "Graph is missing. Initialize the graph first.")
            }
            NodeError::RootNodeNotFound => write!(f, "Root node not found."),
            NodeError::NodeNotFound(ref message) => write!(f, "{}", message),
            NodeError::InvalidNodeId => write!(f, "Invalid node ID provided."),
            NodeError::MissingParentNode => write!(f, "Parent node is not a conversation node."),
            NodeError::MissingLastUpdatedNode => write!(f, "No last updated node found."),
            NodeError::InvalidQuestionNode => write!(f, "Invalid question node provided."),
            NodeError::NoTaskFound => write!(f, "No task found."),
            NodeError::RedisSaveError => write!(f, "Error saving the task process to Redis."),
        }
    }
}

impl Error for NodeError {}

impl TrackProcessV1 {
    // This method adds any node and connects it to the given parent node.
    pub fn add_and_connect_node(
        &mut self,
        parent_node_id: NodeIndex,
        node: NodeV1,
        edge: EdgeV1,
    ) -> Result<&mut Self, NodeError> {
        self.initialize_graph();

        // Confirm the graph is initialized.
        let graph = self.graph.as_mut().ok_or(NodeError::GraphNotInitialized)?;

        // Validate the parent node.
        graph
            .node_weight(parent_node_id)
            .ok_or(NodeError::InvalidNodeId)?;

        // Add the new node and connect it.
        let new_node_id = graph.add_node(node.clone());
        graph.add_edge(parent_node_id, new_node_id, edge);

        // Update the last added node and timestamps.
        self.last_added_node = Some(new_node_id);
        self.last_updated = SystemTime::now();

        // If the new node is a conversation node, update last_added_conversation_node.
        if matches!(node, NodeV1::Conversation(..)) {
            self.last_added_conversation_node = Some(new_node_id);
        }

        Ok(self)
    }

    // This function specifically adds and connects a conversation node.
    pub fn add_and_connect_conversation_node(
        &mut self,
        message: Message,
        source: MessageRole, 
    ) -> Result<&mut Self, NodeError> {
        // Initialize the graph if it's not already initialized.
        self.initialize_graph();

        // Determine the parent node: use the last conversation node if available, or the root node.
        let parent_node_id = self
            .last_added_conversation_node
            .or_else(|| self.root_node)
            .ok_or(NodeError::MissingLastUpdatedNode)?;

        // create new uuid for the conversation node
        let new_conversation_id = Uuid::new_v4();
        // Create the conversation node.
        let node = NodeV1::Conversation(source, message, new_conversation_id.to_string());

        // Use the updated add_and_connect_node method to add and connect the conversation node.
        self.add_and_connect_node(parent_node_id, node, EdgeV1::NextConversation)
    }

    // Refactor these methods to leverage add_and_connect_conversation_node for better reuse.
    pub fn add_user_conversation(&mut self, message: Message) -> Result<&mut Self, NodeError> {
        self.add_and_connect_conversation_node(message, MessageRole::User)
    }

    pub fn add_system_conversation(&mut self, message: Message) -> Result<&mut Self, NodeError> {
        self.add_and_connect_conversation_node(message, MessageRole::System)
    }

    pub fn add_assistant_conversation(&mut self, message: Message) -> Result<&mut Self, NodeError> {
        self.add_and_connect_conversation_node(message, MessageRole::Assistant)
    }

    // Helper methods for adding task, subtask, and question nodes.
    pub fn add_task_node(&mut self, task_description: String) -> Result<NodeIndex, NodeError> {
        let task_node = self
            .graph
            .as_mut()
            .unwrap()
            .add_node(NodeV1::Task(task_description));
        self.graph.as_mut().unwrap().add_edge(
            self.last_added_conversation_node
                .ok_or(NodeError::MissingLastUpdatedNode)?,
            task_node,
            EdgeV1::Task,
        );
        Ok(task_node)
    }

    pub fn add_subtask_node(
        &mut self,
        subtask_description: String,
        parent_node: NodeIndex,
    ) -> Result<NodeIndex, NodeError> {
        let subtask_node = self
            .graph
            .as_mut()
            .unwrap()
            .add_node(NodeV1::Subtask(subtask_description));
        self.graph
            .as_mut()
            .unwrap()
            .add_edge(parent_node, subtask_node, EdgeV1::Subtask);
        Ok(subtask_node)
    }

    pub fn add_question_node(
        &mut self,
        question_content: String,
        subtask_node: NodeIndex,
    ) -> Result<NodeIndex, NodeError> {
        let graph = self.graph.as_mut().unwrap(); // Unwrap the graph for convenience
        let question_node = graph.add_node(NodeV1::Question(question_content));
        graph.add_edge(subtask_node, question_node, EdgeV1::Question);
        Ok(question_node)
    }
}
