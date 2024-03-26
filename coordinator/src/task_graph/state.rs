use log::debug;
use crate::task_graph::graph_model::EdgeV1;
use crate::task_graph::graph_model::{NodeV1, TrackProcessV1};
use petgraph::graph::NodeIndex;
use petgraph::visit::EdgeRef;
use petgraph::visit::{Dfs, IntoNodeReferences, Visitable};
use petgraph::Graph;

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
    /// Returns the node ID of the last conversation node.
    pub fn last_conversation_node_id(&self) -> Option<NodeIndex> {
        self.last_added_conversation_node
    }

    /// Determines the processing stage of the last conversation in the graph.
    /// We never persist the graph in the Redis just with a Root node. 
    /// Hence we make an assumption that the last conversation node is available.
    pub fn last_conversation_processing_stage(
        &self,
    ) -> (ConversationProcessingStage, Option<NodeIndex>) {
        // Check if the graph is initialized.
        if let Some(ref graph) = self.graph {
            // Proceed if the graph is present and the last conversation node is known.
            if let Some(last_conversation_node_id) = self.last_added_conversation_node {
                // Check for the existence of a 'Process' edge from the last conversation node.
                let process_edge_exists = graph
                    .edges_directed(last_conversation_node_id, petgraph::Direction::Outgoing)
                    .any(|edge| matches!(edge.weight(), EdgeV1::Process));

                if process_edge_exists {
                    // Determine the processing stage based on the presence of 'Question' and 'Answer' edges.
                    let has_questions = graph
                        .edges_directed(last_conversation_node_id, petgraph::Direction::Outgoing)
                        .any(|e| matches!(e.weight(), EdgeV1::Question));
                    let has_answers = graph
                        .edges_directed(last_conversation_node_id, petgraph::Direction::Outgoing)
                        .any(|e| matches!(e.weight(), EdgeV1::Answer));

                    let processing_stage = match (has_questions, has_answers) {
                        (true, false) => ConversationProcessingStage::QuestionsGenerated,
                        (true, true) => ConversationProcessingStage::AnswersGenerated,
                        _ => ConversationProcessingStage::Unknown,
                    };

                    return (processing_stage, Some(last_conversation_node_id));
                }

                // If no Process edge is found, the conversation awaits user input.
                debug!("No 'Process' edge found from the last conversation node. Awaiting user response");
                (
                    ConversationProcessingStage::AwaitingUserInput,
                    Some(last_conversation_node_id),
                )
            } else {
                // If there's no last conversation node, the stage is unknown.
                (ConversationProcessingStage::Unknown, None)
            }
        } else {
            // Log that the graph is not initialized and return default values.
            debug!("Graph is not initialized. Unable to determine the last conversation processing stage.");
            (ConversationProcessingStage::Unknown, None)
        }
    }
}

/// Prints the graph hierarchy starting from the root node.
pub fn print_graph_hierarchy<N, E>(graph: &Graph<N, E>)
where
    N: std::fmt::Debug,
    E: std::fmt::Debug,
{
    // Initialize depth-first search (DFS) to traverse the graph.
    let mut dfs = Dfs::new(&graph, graph.node_indices().next().unwrap());

    while let Some(node_id) = dfs.next(&graph) {
        // The depth here is used to indent the output for hierarchy visualization.
        let depth = dfs.stack.len();
        let indent = " ".repeat(depth * 4); // Indent based on depth.

        if let Some(node) = graph.node_weight(node_id) {
            println!("{}{:?} (Node ID: {:?})", indent, node, node_id);
        }

        // Print edges and connected nodes.
        for edge in graph.edges(node_id) {
            println!(
                "{}--> Edge: {:?}, connects to Node ID: {:?}",
                " ".repeat((depth + 1) * 4),
                edge.weight(),
                edge.target()
            );
        }
    }
}
