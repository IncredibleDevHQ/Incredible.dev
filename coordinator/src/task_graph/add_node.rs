use crate::task_graph::graph_model::TrackProcessV1;
use crate::task_graph::graph_model::{EdgeV1, NodeV1};
use anyhow::Result;
use common::llm_gateway::api::{Message, MessageSource};
use log::error;
use petgraph::graph::NodeIndex;
use std::error::Error;
use std::fmt;

#[derive(Debug)]
pub enum NodeError {
    NodeNotFound(String),
    InvalidNodeId,
    InvalidParentNode,
    MissingLastUpdatedNode,
}

impl fmt::Display for NodeError {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        match *self {
            NodeError::NodeNotFound(ref message) => write!(f, "{}", message),
            NodeError::InvalidNodeId => write!(f, "Invalid node ID provided."),
            NodeError::InvalidParentNode => write!(f, "Parent node is not a conversation node."),
            NodeError::MissingLastUpdatedNode => write!(f, "No last updated node found."),
        }
    }
}

impl Error for NodeError {}

impl TrackProcessV1 {
    pub fn add_and_connect_node(
        &mut self,
        parent_node_id: NodeIndex,
        node: NodeV1,
        edge: EdgeV1,
    ) -> Result<&mut Self, NodeError> {
        // Validate the parent node.
        self.graph
            .node_weight(parent_node_id)
            .ok_or_else(|| NodeError::InvalidNodeId)?;

        // Add the new node and connect it to the specified parent node.
        let new_node_id = self.graph.add_node(node);
        self.graph.add_edge(parent_node_id, new_node_id, edge);

        // Update the last added node with the new node's ID.
        self.last_added_node = Some(new_node_id);

        // Return self for chaining.
        Ok(self)
    }

    pub fn add_and_connect_to_last_updated_node(
        &mut self,
        node: NodeV1,
        edge: EdgeV1,
    ) -> Result<&mut Self, NodeError> {
        let parent_node_id = self
            .last_added_node
            .ok_or_else(|| NodeError::MissingLastUpdatedNode)?;

        // Use the general add_and_connect_node function to add and connect to the last updated node.
        self.add_and_connect_node(parent_node_id, node, edge)
    }

    pub fn add_and_connect_conversation_node(
        &mut self,
        message: Message,
        source: MessageSource,
    ) -> Result<&mut Self, NodeError> {
        // Determine the parent node ID: either the last added node or root if none.
        let parent_node_id = self.last_added_node.unwrap_or(self.root_node);

        // Validate the parent node.
        let parent_node = self
            .graph
            .node_weight(parent_node_id)
            .ok_or_else(|| NodeError::InvalidNodeId)?;

        // Ensure the parent node is a conversation node.
        if !matches!(parent_node, NodeV1::Conversation(..)) {
            return Err(NodeError::InvalidParentNode);
        }

        // Add the new conversation node and connect it to the parent node.
        let new_node_id = self
            .graph
            .add_node(NodeV1::Conversation(source, message, self.uuid));
        self.graph
            .add_edge(parent_node_id, new_node_id, EdgeV1::NextConversation);

        // Update the last added node with the new node's ID.
        self.last_added_node = Some(new_node_id);

        // Return self for chaining.
        Ok(self)
    }

    // Add a user message as a conversation node and connect it.
    pub fn add_user_conversation(&mut self, message: Message) -> Result<&mut Self, NodeError> {
        self.add_and_connect_conversation_node(message, MessageSource::User)
    }

    // Add a system message as a conversation node and connect it.
    pub fn add_system_conversation(&mut self, message: Message) -> Result<&mut Self, NodeError> {
        self.add_and_connect_conversation_node(message, MessageSource::System)
    }

    // Add an assistant message as a conversation node and connect it.
    pub fn add_assistant_conversation(&mut self, message: Message) -> Result<&mut Self, NodeError> {
        self.add_and_connect_conversation_node(message, MessageSource::Assistant)
    }
}
