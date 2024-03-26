use crate::task_graph::graph_model::EdgeV1;
use crate::task_graph::graph_model::{NodeV1, TrackProcessV1};
use log::debug;
use petgraph::graph::NodeIndex;
use petgraph::visit::EdgeRef;
use petgraph::visit::{Dfs, IntoNodeReferences, Visitable};
use petgraph::Graph;
use crate::task_graph::add_node::NodeError;

use common::models::{Subtask, Task, TaskList, TaskListResponse};

/// Enum representing the various stages following the last conversation.
#[derive(Debug, PartialEq)]
pub enum ConversationProcessingStage {
    AwaitingUserInput,
    TasksAndQuestionsGenerated, // Indicates that tasks and questions are generated.
    AnswersGenerated,           // Indicates that answers to the generated questions are available.
    GraphNotInitialized,
    OnlyRootNodeExists,
    Unknown, // State cannot be determined or does not fit the other categories.
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
    /// Determines the processing stage of the last conversation in the graph.
    pub fn last_conversation_processing_stage(
        &self,
    ) -> (ConversationProcessingStage, Option<NodeIndex>) {
        match &self.graph {
            Some(graph) => {
                // Check if only the root node exists.
                if graph.node_count() == 1 {
                    return (
                        ConversationProcessingStage::OnlyRootNodeExists,
                        self.root_node,
                    );
                }

                // Proceed if there are more nodes beyond the root.
                if let Some(last_conversation_node_id) = self.last_added_conversation_node {
                    // Check for the existence of a 'Process' edge to a Task node from the last conversation node.
                    let process_to_task_edge_exists = graph
                        .edges_directed(last_conversation_node_id, petgraph::Direction::Outgoing)
                        .any(|edge| {
                            matches!(edge.weight(), EdgeV1::Process)
                                && matches!(graph.node_weight(edge.target()), Some(NodeV1::Task(_)))
                        });

                    let processing_stage = if process_to_task_edge_exists {
                        // If there's a Process edge to a Task node, we know tasks and associated questions were generated.
                        ConversationProcessingStage::TasksAndQuestionsGenerated
                    } else {
                        // If no Process edge to a Task node is found, we're awaiting user input or further actions.
                        ConversationProcessingStage::AwaitingUserInput
                    };

                    (processing_stage, Some(last_conversation_node_id))
                } else {
                    // If there's no last conversation node ID available, the stage is unknown.
                    (ConversationProcessingStage::Unknown, None)
                }
            }
            None => {
                // If the graph is not initialized, return the appropriate stage.
                (ConversationProcessingStage::GraphNotInitialized, None)
            }
        }
    }

    /// Extracts tasks, subtasks, and questions from the graph and constructs a `TaskListResponse`.
    pub fn extract_task_list_response(&self) -> Result<TaskListResponse, NodeError> {
        // Check if the graph is initialized.
        let graph = self.graph.as_ref().ok_or(NodeError::MissingGraph)?;

        // Ensure the root node exists.
        let root_node = self.root_node.ok_or(NodeError::RootNodeNotFound)?;

        let mut tasks = Vec::new();

        // Iterate through all nodes that are direct children of the root and are Task nodes.
        for task_edge in graph.edges_directed(root_node, petgraph::Direction::Outgoing) {
            if let Some(NodeV1::Task(task_description)) = graph.node_weight(task_edge.target()) {
                let mut subtasks = Vec::new();

                // For each Task node, find its Subtask nodes.
                for subtask_edge in
                    graph.edges_directed(task_edge.target(), petgraph::Direction::Outgoing)
                {
                    if let Some(NodeV1::Subtask(subtask_description)) =
                        graph.node_weight(subtask_edge.target())
                    {
                        let mut questions = Vec::new();

                        // For each Subtask node, find its Question nodes.
                        for question_edge in graph
                            .edges_directed(subtask_edge.target(), petgraph::Direction::Outgoing)
                        {
                            if let Some(NodeV1::Question(_, question)) =
                                graph.node_weight(question_edge.target())
                            {
                                questions.push(question.clone());
                            }
                        }

                        let subtask = Subtask {
                            subtask: subtask_description.clone(),
                            questions,
                        };
                        subtasks.push(subtask);
                    }
                }

                let task = Task {
                    task: task_description.clone(),
                    subtasks,
                };
                tasks.push(task);
            }
        }

        Ok(TaskListResponse {
            tasks: Some(TaskList { tasks }),
            ask_user: None,
        })
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
