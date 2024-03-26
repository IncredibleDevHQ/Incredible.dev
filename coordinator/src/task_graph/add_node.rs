use crate::task_graph::graph_model::TrackProcessV1;
use crate::task_graph::graph_model::{EdgeV1, NodeV1};
use anyhow::Result;
use common::llm_gateway::api::{Message, MessageSource};
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
    // This method remains the same, adding any node and connecting it to a given parent node.
    pub fn add_and_connect_node(
        &mut self,
        parent_node_id: NodeIndex,
        node: NodeV1,
        edge: EdgeV1,
    ) -> Result<&mut Self, NodeError> {
        self.graph
            .node_weight(parent_node_id)
            .ok_or_else(|| NodeError::InvalidNodeId)?;

        let new_node_id = self.graph.add_node(node);
        self.graph.add_edge(parent_node_id, new_node_id, edge);

        self.last_added_node = Some(new_node_id);
        Ok(self)
    }

    // This method adds a node and connects it to the last updated node.
    pub fn add_and_connect_to_last_updated_node(
        &mut self,
        node: NodeV1,
        edge: EdgeV1,
    ) -> Result<&mut Self, NodeError> {
        let parent_node_id = self
            .last_added_node
            .ok_or_else(|| NodeError::MissingLastUpdatedNode)?;

        self.add_and_connect_node(parent_node_id, node, edge)
    }

    // This method adds a conversation node and connects it using the last conversation node.
    pub fn add_and_connect_conversation_node(
        &mut self,
        message: Message,
        source: MessageSource,
    ) -> Result<&mut Self, NodeError> {
        let node = NodeV1::Conversation(source, message, self.uuid);
        let edge = EdgeV1::NextConversation;

        // Use the last added conversation node or default to the root node if it's not available.
        let parent_node_id = self.last_added_conversation_node.unwrap_or(self.root_node);
        
        let result = self.add_and_connect_node(parent_node_id, node, edge)?;
        self.last_added_conversation_node = self.last_added_node;
        Ok(result)
    }

    // Refactor these methods to leverage add_and_connect_conversation_node for better reuse.
    pub fn add_user_conversation(&mut self, message: Message) -> Result<&mut Self, NodeError> {
        self.add_and_connect_conversation_node(message, MessageSource::User)
    }

    pub fn add_system_conversation(&mut self, message: Message) -> Result<&mut Self, NodeError> {
        self.add_and_connect_conversation_node(message, MessageSource::System)
    }

    pub fn add_assistant_conversation(&mut self, message: Message) -> Result<&mut Self, NodeError> {
        self.add_and_connect_conversation_node(message, MessageSource::Assistant)
    }
}
