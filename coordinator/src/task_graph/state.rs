use crate::task_graph::graph_model::{TrackProcessV1, NodeV1};
use petgraph::graph::NodeIndex;

impl TrackProcessV1 {
    /// Finds the last conversation node and returns its type and ID.
    pub fn last_conversation_state(&self) -> Option<(NodeV1, NodeIndex)> {
        // Reverse iterate through the graph to find the last conversation node.
        let mut last_conversation = None;
        for node_index in self.graph.node_indices().rev() {
            if let Some(node) = self.graph.node_weight(node_index) {
                if matches!(node, NodeV1::Conversation(..)) {
                    last_conversation = Some((*node.clone(), node_index));
                    break;
                }
            }
        }
        last_conversation
    }
}
