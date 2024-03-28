use crate::task_graph::add_node::NodeError;
use crate::task_graph::graph_model::EdgeV1;
use crate::task_graph::graph_model::{NodeV1, TrackProcessV1};
use common::llm_gateway::api::{Message, MessageSource, Messages};
use log::debug;
use petgraph::graph::DiGraph;
use petgraph::graph::NodeIndex;
use petgraph::visit::EdgeRef;
use petgraph::visit::{Dfs, IntoNodeReferences, Visitable};
use petgraph::Graph;

use common::models::{Subtask, Task, TaskList};
use serde::de;

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
                            matches!(edge.weight(), EdgeV1::Task)
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

    /// Extracts a `TaskListResponse` by traversing the graph from the root node and collecting tasks.
    // Helper function to extract questions for a given subtask node.
    fn extract_questions(
        &self,
        subtask_node: NodeIndex,
        graph: &DiGraph<NodeV1, EdgeV1>,
    ) -> Vec<String> {
        graph
            .edges_directed(subtask_node, petgraph::Direction::Outgoing)
            .filter_map(|question_edge| {
                if let Some(NodeV1::Question(_, question)) =
                    graph.node_weight(question_edge.target())
                {
                    Some(question.clone())
                } else {
                    None
                }
            })
            .collect()
    }

    // Helper function to extract subtasks for a given task node.
    fn extract_subtasks(
        &self,
        task_node: NodeIndex,
        graph: &DiGraph<NodeV1, EdgeV1>,
    ) -> Vec<Subtask> {
        graph
            .edges_directed(task_node, petgraph::Direction::Outgoing)
            .filter_map(|subtask_edge| {
                if let Some(NodeV1::Subtask(subtask_description)) =
                    graph.node_weight(subtask_edge.target())
                {
                    let questions = self.extract_questions(subtask_edge.target(), graph);
                    Some(Subtask {
                        subtask: subtask_description.clone(),
                        questions,
                    })
                } else {
                    None
                }
            })
            .collect()
    }

    // Extracts the task list response from the graph.
    // iterate from the root node to find the first conversation node with outgoing Task edges.
    // then collect all Task edges to find the tasks, then the subtasks for each task, and the nested questions.
    pub fn extract_task_list_response(&self) -> Result<TaskList, NodeError> {
        // Ensure the graph and root node are initialized.
        let graph = self.graph.as_ref().ok_or(NodeError::GraphNotInitialized)?;
        let mut current_node = self.root_node.ok_or(NodeError::RootNodeNotFound)?;

        // Traverse the graph to find the first conversation node with outgoing Task edges.
        while graph
            .edges_directed(current_node, petgraph::Direction::Outgoing)
            .any(|edge| !matches!(edge.weight(), EdgeV1::Task))
        {
            if let Some(next_node) = graph
                .edges_directed(current_node, petgraph::Direction::Outgoing)
                .find_map(|edge| {
                    if matches!(edge.weight(), EdgeV1::NextConversation) {
                        Some(edge.target())
                    } else {
                        None
                    }
                })
            {
                current_node = next_node;
            } else {
                // If no further conversation nodes are found, break the loop.
                break;
            }
        }

        // Collect all Task edges from the current conversation node.
        let task_edges = graph
            .edges_directed(current_node, petgraph::Direction::Outgoing)
            .filter_map(|edge| {
                if matches!(edge.weight(), EdgeV1::Task) {
                    Some(edge.target())
                } else {
                    None
                }
            })
            .collect::<Vec<_>>();

        // Use the helper functions to construct the TaskListResponse.
        let tasks = task_edges
            .iter()
            .filter_map(|&task_node| {
                if let Some(NodeV1::Task(task_description)) = graph.node_weight(task_node) {
                    let subtasks = self.extract_subtasks(task_node, graph);
                    Some(Task {
                        task: task_description.clone(),
                        subtasks,
                    })
                } else {
                    None
                }
            })
            .collect::<Vec<_>>();

        Ok(TaskList {
            tasks: Some(tasks),
            ask_user: None,
        })
    }
    // Helper functions (extract_subtasks and extract_questions) remain the same as previously defined.

    // collects the history of conversations in the form of Messages, which is the
    // desired format for the response to the user.
    pub fn collect_conversation_messages(&self) -> Result<Messages, NodeError> {
        // Verify that the graph is initialized and the root node exists.
        let graph = self.graph.as_ref().ok_or(NodeError::GraphNotInitialized)?;
        let root_node = self.root_node.ok_or(NodeError::RootNodeNotFound)?;

        let mut messages = Vec::new();

        for node_index in graph.node_indices() {
            if let Some(NodeV1::Conversation(source, message, _)) = graph.node_weight(node_index) {
                let role = match source {
                    MessageSource::User => "user",
                    MessageSource::Assistant => "assistant",
                    MessageSource::System => "system",
                };

                // Depending on the message variant, extract the content.
                let message_content = match message {
                    Message::PlainText { content, .. } => content,
                    //Message::FunctionReturn { content, .. } => content,
                    // Here, it's treated as an empty string or you can choose to skip adding to messages.
                    _ => "",
                };

                let message = Message::new_text(role, message_content);
                messages.push(message);
            }
        }

        Ok(Messages { messages })
    }

    // print the nodes and edges of the graph in a hierarchical manner.
    pub fn print_graph_hierarchy(&self)
    {
        // If the graph is not initialized, return early.
        if self.graph.is_none() {
            println!("Graph is not initialized. Cannot print the graph.");
            return;
        }

        let graph = self.graph.as_ref().unwrap();
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
}
