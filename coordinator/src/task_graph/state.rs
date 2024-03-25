use petgraph::graph::NodeIndex;
use petgraph::visit::EdgeRef;
use crate::task_graph::graph_model::EdgeV1;
use crate::task_graph::graph_model::{NodeV1, TrackProcessV1};

/// Enum representing the various stages following the last conversation.
#[derive(Debug)]
pub enum ConversationProcessingStage {
    AwaitingUserInput,
    QuestionsGenerated, // Implies that tasks are also generated as they are coupled.
    AnswersGenerated,   // Indicates that answers to the generated questions are available.
    Unknown,            // State cannot be determined or does not fit the other categories.
}

impl TrackProcessV1 {
    /// Finds the node ID of the last conversation node in the graph.
    pub fn last_conversation_node_id(&self) -> Option<NodeIndex> {
        self.graph.node_indices().rev().find_map(|node_index| {
            match self.graph.node_weight(node_index) {
                Some(NodeV1::Conversation(..)) => Some(node_index),
                _ => None,
            }
        })
    }

    pub fn last_conversation_processing_stage(&self) -> ConversationProcessingStage {
        self.last_conversation_node_id()
            .map_or(ConversationProcessingStage::Unknown, |node_id| {
                // Retrieve the outgoing edges of the last conversation node and look for a Process edge.
                let process_edge = self
                    .graph
                    .edges_directed(node_id, petgraph::Direction::Outgoing)
                    .find(|edge| matches!(edge.weight(), EdgeV1::Process));

                match process_edge {
                    Some(edge) => {
                        // Determine the type of node the Process edge is pointing to.
                        match self.graph.node_weight(edge.target()) {
                            Some(NodeV1::Task(_)) | Some(NodeV1::Question(_, _)) => {
                                // Check if there are any Question or Answer edges connected to the target node.
                                let has_questions = self
                                    .graph
                                    .edges_directed(edge.target(), petgraph::Direction::Outgoing)
                                    .any(|e| matches!(e.weight(), EdgeV1::Question));
                                let has_answers = self
                                    .graph
                                    .edges_directed(edge.target(), petgraph::Direction::Outgoing)
                                    .any(|e| matches!(e.weight(), EdgeV1::Answer));

                                match (has_questions, has_answers) {
                                    (true, false) => {
                                        ConversationProcessingStage::QuestionsGenerated
                                    }
                                    (true, true) => ConversationProcessingStage::AnswersGenerated,
                                    _ => ConversationProcessingStage::Unknown,
                                }
                            }
                            _ => ConversationProcessingStage::Unknown,
                        }
                    }
                    None => ConversationProcessingStage::AwaitingUserInput,
                }
            })
    }
}
