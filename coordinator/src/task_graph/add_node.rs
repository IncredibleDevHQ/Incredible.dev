use std::fmt;
use log::error;
use anyhow::Result;
use std::error::Error;
use crate::task_graph::graph_model::TrackProcessV1;
use petgraph::graph::NodeIndex;
use crate::task_graph::graph_model::{NodeV1, EdgeV1};
use common::llm_gateway::api::{Message, MessageSource};

#[derive(Debug)]
pub enum NodeError {
    NodeNotFound(String),
}

impl fmt::Display for NodeError {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        match *self {
            NodeError::NodeNotFound(ref message) => write!(f, "{}", message),
        }
    }
}

impl Error for NodeError {}

impl TrackProcessV1 {
    pub fn add_and_connect_node(
        &mut self,
        node_id: NodeIndex,
        new_node_value: NodeV1,
        connecting_edge: EdgeV1,
    ) -> Result<NodeIndex, NodeError> {
        if self.graph.node_weight(node_id).is_none() {
            let error_message = format!("No node found with the specified NodeIndex: {:?}", node_id);
            error!("{}", error_message);
            return Err(NodeError::NodeNotFound(error_message));
        }

        let new_node_id = self.graph.add_node(new_node_value);
        self.graph.add_edge(node_id, new_node_id, connecting_edge);
        Ok(new_node_id)
    }

    // Function to add a User message as a Conversation node
    pub fn add_user_conversation(
        &mut self,
        node_id: NodeIndex,
        message: Message,
    ) -> Result<NodeIndex, NodeError> {
        self.add_and_connect_node(
            node_id,
            NodeV1::Conversation(MessageSource::User, message, self.uuid),
            EdgeV1::NextConversation,
        )
    }

    // Function to add a System message as a Conversation node
    pub fn add_system_conversation(
        &mut self,
        node_id: NodeIndex,
        message: Message,
    ) -> Result<NodeIndex, NodeError> {
        self.add_and_connect_node(
            node_id,
            NodeV1::Conversation(MessageSource::System, message, self.uuid), 
            EdgeV1::NextConversation,
        )
    }

    // Function to add an Assistant message as a Conversation node
    pub fn add_assistant_conversation(
        &mut self,
        node_id: NodeIndex,
        message: Message,
    ) -> Result<NodeIndex, NodeError> {
        self.add_and_connect_node(
            node_id,
            NodeV1::Conversation(MessageSource::Assistant, message, self.uuid), 
            EdgeV1::NextConversation,
        )
    }
}
