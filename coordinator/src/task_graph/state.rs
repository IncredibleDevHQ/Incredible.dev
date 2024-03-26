use crate::task_graph::graph_model::EdgeV1;
use crate::task_graph::graph_model::{NodeV1, TrackProcessV1};
use petgraph::graph::NodeIndex;
use petgraph::visit::EdgeRef;

/// Enum representing the various stages following the last conversation.
#[derive(Debug, PartialEq)]
pub enum ConversationProcessingStage {
    AwaitingUserInput,
    QuestionsGenerated, // Implies that tasks are also generated as they are coupled.
    AnswersGenerated,   // Indicates that answers to the generated questions are available.
    Unknown,            // State cannot be determined or does not fit the other categories.
}

impl TrackProcessV1 {
    /// Finds the node ID of the last conversation node in the graph.
    /// This helps in understanding the last interaction point in the conversation history.
    pub fn last_conversation_node_id(&self) -> Option<NodeIndex> {
        // Iterate in reverse through all nodes to find the latest conversation node.
        self.graph.node_indices().rev().find_map(|node_index| {
            match self.graph.node_weight(node_index) {
                // Return the node index if it's a conversation node.
                Some(NodeV1::Conversation(..)) => Some(node_index),
                // Continue the search if it's not a conversation node.
                _ => None,
            }
        })
    }

    /// Determines the processing stage of the last conversation in the graph.
    /// This function is crucial for identifying the state of the conversation to decide the subsequent actions.
    pub fn last_conversation_processing_stage(
        &self,
    ) -> (ConversationProcessingStage, Option<NodeIndex>) {
        let last_conversation_node_id = self.last_conversation_node_id();

        // Determine the conversation processing stage based on the last conversation node.
        let processing_stage =
            last_conversation_node_id.map_or(ConversationProcessingStage::Unknown, |node_id| {
                // Retrieve the outgoing edges of the last conversation node.
                // We're particularly interested in finding a 'Process' edge which indicates progression in the task processing.
                let process_edge = self
                    .graph
                    .edges_directed(node_id, petgraph::Direction::Outgoing)
                    .find(|edge| matches!(edge.weight(), EdgeV1::Process));

                match process_edge {
                    Some(edge) => {
                        // Identify the type of node the Process edge is pointing to.
                        // This helps in understanding what stage the conversation is at: task generation, question generation, or answer processing.
                        match self.graph.node_weight(edge.target()) {
                            Some(NodeV1::Task(_)) | Some(NodeV1::Question(_, _)) => {
                                // Evaluate if there are connected Question or Answer nodes to ascertain the processing stage further.
                                let has_questions = self
                                    .graph
                                    .edges_directed(edge.target(), petgraph::Direction::Outgoing)
                                    .any(|e| matches!(e.weight(), EdgeV1::Question));
                                let has_answers = self
                                    .graph
                                    .edges_directed(edge.target(), petgraph::Direction::Outgoing)
                                    .any(|e| matches!(e.weight(), EdgeV1::Answer));

                                // Determine the processing stage based on the presence of question and answer nodes.
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
                    None => {
                        // If there's no Process edge, it implies we are awaiting further user input.
                        ConversationProcessingStage::AwaitingUserInput
                    }
                }
            });

        // Return both the processing stage and the last conversation node ID to provide a complete context of the conversation's current state.
        (processing_stage, last_conversation_node_id)
    }
}
