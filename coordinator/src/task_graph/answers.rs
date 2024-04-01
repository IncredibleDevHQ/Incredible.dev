use crate::task_graph::add_node::NodeError;
use crate::task_graph::graph_model::{NodeV1, TrackProcessV1};
use petgraph::graph::{DiGraph, NodeIndex};
use petgraph::visit::EdgeRef;

use std::ops::Range;

use common::models::{ TaskDetailsWithContext, TasksQuestionsAnswersDetails};
use common::CodeContext;

impl TrackProcessV1 {
    // Collects task details along with their associated questions, answers, and code contexts from the graph.
    pub fn collect_tasks_questions_answers_contexts(
        &self,
    ) -> Result<TasksQuestionsAnswersDetails, NodeError> {
        // Check if the graph is initialized, return an error if not.
        let graph = self.graph.as_ref().ok_or(NodeError::GraphNotInitialized)?;
    
        let mut tasks_details = Vec::new();
    
        // Iterate through all nodes in the graph to find task nodes.
        for node_index in graph.node_indices() {
            // Check if the current node is a task node.
            if let NodeV1::Task(task_description) = &graph[node_index] {
                let mut questions = Vec::new();
                let mut answers = Vec::new();
                let mut code_contexts = Vec::new();
    
                // Collect all questions, answers, and code contexts related to this task.
                graph.edges_directed(node_index, petgraph::Direction::Outgoing).for_each(|edge| {
                    // For each subtask node connected to the task...
                    if let Some(NodeV1::Subtask(_)) = graph.node_weight(edge.target()) {
                        // Iterate over all edges from the subtask to collect questions.
                        graph.edges_directed(edge.target(), petgraph::Direction::Outgoing).for_each(|subtask_edge| {
                            // For each question node connected to the subtask...
                            if let Some(NodeV1::Question(question)) = graph.node_weight(subtask_edge.target()) {
                                questions.push(question.clone());
    
                                // Iterate over all edges from the question to collect answers and their associated code contexts.
                                graph.edges_directed(subtask_edge.target(), petgraph::Direction::Outgoing).for_each(|answer_edge| {
                                    if let Some(NodeV1::Answer(answer)) = graph.node_weight(answer_edge.target()) {
                                        answers.push(answer.clone());
    
                                        // Collect all code contexts associated with this answer.
                                        graph.edges_directed(answer_edge.target(), petgraph::Direction::Outgoing).for_each(|context_edge| {
                                            if let Some(NodeV1::CodeContext(context)) = graph.node_weight(context_edge.target()) {
                                                code_contexts.push(context.clone());
                                            }
                                        });
                                    }
                                });
                            }
                        });
                    }
                });
    
                // Merge overlapping code contexts to avoid redundancy.
                let merged_code_contexts = merge_code_contexts(&code_contexts);
    
                // Store the aggregated task details including questions, answers, and both raw and merged code contexts.
                tasks_details.push(TaskDetailsWithContext {
                    task_id: node_index.index(), // Use the node index as a unique identifier for the task.
                    task_description: task_description.clone(),
                    questions,
                    answers,
                    code_contexts,
                    merged_code_contexts,
                });
            }
        }
    
        // Return the structured details of tasks along with their associated questions, answers, and code contexts.
        Ok(TasksQuestionsAnswersDetails {
            root_node_id: self.root_node.ok_or(NodeError::RootNodeNotFound)?.index(),
            tasks: tasks_details,
        })
    }
}


pub fn merge_code_contexts(contexts: &Vec<CodeContext>) -> Vec<CodeContext> {
    let mut merged_contexts: Vec<CodeContext> = Vec::new();

    for context in contexts {
        let existing_context = merged_contexts.iter_mut().find(|c| c.path == context.path && c.repo == context.repo && c.branch == context.branch);

        match existing_context {
            Some(existing) => {
                existing.ranges.extend(context.ranges.clone());
                existing.ranges = merge_ranges(&existing.ranges.clone());
            },
            None => {
                let mut new_context = context.clone();
                new_context.ranges = merge_ranges(&new_context.ranges);
                merged_contexts.push(new_context);
            }
        }
    }
    merged_contexts
}

fn merge_ranges(ranges: &Vec<Range<usize>>) -> Vec<Range<usize>> {
    let mut merged_ranges: Vec<Range<usize>> = Vec::new();
    let mut sorted_ranges = ranges.clone();
    sorted_ranges.sort_by(|a, b| a.start.cmp(&b.start));

    for range in sorted_ranges {
        if let Some(last) = merged_ranges.last_mut() {
            if last.end >= range.start {
                // Extend the range if overlapping or contiguous
                last.end = last.end.max(range.end);
            } else {
                merged_ranges.push(range.clone());
            }
        } else {
            merged_ranges.push(range.clone());
        }
    }

    merged_ranges
}

