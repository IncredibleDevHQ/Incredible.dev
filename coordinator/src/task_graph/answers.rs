use crate::task_graph::graph_model::{TrackProcessV1, NodeV1, EdgeV1};
use crate::task_graph::add_node::NodeError;
use petgraph::visit::EdgeRef;
use petgraph::graph::{DiGraph, NodeIndex};

use common::CodeContext;
#[derive(Debug, Clone)]
struct TasksAnswersDetails {
    root_node_id: usize,
    task_details: Vec<TaskDetailsWithContext>,
}

#[derive(Debug, Clone)]
struct AnswerAndContexts {
    answers: Vec<String>,
    code_contexts: Vec<CodeContext>,
    merged_code_contexts: Vec<CodeContext>, // New field to store merged contexts
}

#[derive(Debug, Clone)]
struct TaskDetailsWithContext {
    task_id: usize,
    task_description: String,
    answer_and_contexts: Vec<AnswerAndContexts>,
}

impl TrackProcessV1 {
    pub fn collect_complete_task_details(&self) -> Result<TasksAnswersDetails, NodeError> {
        let graph = self.graph.as_ref().ok_or(NodeError::GraphNotInitialized)?;
        let root_node_id = self.root_node.ok_or(NodeError::RootNodeNotFound)?.index();
        let task_details = self.collect_tasks_answers_contexts()?;

        Ok(TasksAnswersDetails {
            root_node_id,
            task_details,
        })
    }

    pub fn collect_tasks_answers_contexts(&self) -> Result<Vec<TaskDetailsWithContext>, NodeError> {
        let graph = self.graph.as_ref().ok_or(NodeError::GraphNotInitialized)?;

        let mut task_details_with_context = Vec::new();

        for task_node in graph.node_indices().filter_map(|n| match &graph[n] {
            NodeV1::Task(desc) => Some((n, desc.clone())),
            _ => None,
        }) {
            let task_id = task_node.0.index();
            let task_description = task_node.1;

            let mut answer_contexts = Vec::new();

            // Breadth-first search from the task node to find and aggregate answers and their code contexts.
            let mut visit_queue = vec![task_node.0];
            while let Some(current_node) = visit_queue.pop() {
                match &graph[current_node] {
                    NodeV1::Question(_) => {
                        let (answers, contexts) =
                            self.find_answers_and_contexts_for_question(current_node, graph);
                        if !answers.is_empty() {
                            let merged_contexts = merge_code_contexts(&contexts);
                            let answer_context = AnswerAndContexts {
                                answers,
                                code_contexts: contexts,
                                merged_code_contexts: merged_contexts, // Store the merged contexts
                            };
                            answer_contexts.push(answer_context);
                        }
                    }
                    NodeV1::Subtask(_) => {
                        visit_queue.extend(
                            graph
                                .edges_directed(current_node, petgraph::Direction::Outgoing)
                                .map(|edge| edge.target()),
                        );
                    }
                    _ => {}
                }
            }

            let task_context = TaskDetailsWithContext {
                task_id,
                task_description,
                answer_and_contexts: answer_contexts,
            };

            task_details_with_context.push(task_context);
        }

        Ok(task_details_with_context)
    }

    fn find_answers_and_contexts_for_question(
        &self,
        question_node: NodeIndex,
        graph: &DiGraph<NodeV1, EdgeV1>,
    ) -> (Vec<String>, Vec<CodeContext>) {
        let mut answers = Vec::new();
        let mut contexts = Vec::new();

        for edge in graph.edges_directed(question_node, petgraph::Direction::Outgoing) {
            if let EdgeV1::Answer = edge.weight() {
                if let NodeV1::Answer(answer) = &graph[edge.target()] {
                    answers.push(answer.clone());
                    contexts.extend(
                        graph
                            .edges_directed(edge.target(), petgraph::Direction::Outgoing)
                            .filter_map(|context_edge| match &graph[context_edge.target()] {
                                NodeV1::CodeContext(context) => Some(context.clone()),
                                _ => None,
                            }),
                    );
                }
            }
        }

        (answers, contexts)
    }
}

fn merge_code_contexts(contexts: &[CodeContext]) -> Vec<CodeContext> {
    // Merge the contexts based on file paths and ranges.
    // This requires a more elaborate logic to merge overlapping ranges for the same file.
    // Placeholder implementation:
    contexts.to_vec() // Placeholder for actual merge logic.
}
