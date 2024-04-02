use std::ops::Range;

use crate::task_graph::add_node::NodeError;
use crate::task_graph::graph_model::{EdgeV1, NodeV1, TrackProcessV1};
use crate::task_graph::redis::save_task_process_to_redis;

use petgraph::graph::{DiGraph, NodeIndex};
use petgraph::visit::EdgeRef;

use common::models::{TaskDetailsWithContext, TasksQuestionsAnswersDetails};
use common::CodeContext;

use log::error;

impl TrackProcessV1 {
    // Collects task details along with their associated questions, answers, and code contexts from the graph.
    pub fn collect_tasks_questions_answers_contexts(
        &self,
    ) -> Result<TasksQuestionsAnswersDetails, NodeError> {
        // Check if the graph is initialized, return an error if not.
        let graph = self.graph.as_ref().ok_or(NodeError::GraphNotInitialized)?;

        let mut tasks_details = Vec::new();
        let mut answer_summary: Option<String> = None;

        // Iterate through all nodes to find the AnswerSummary node if it exists.
        for node_index in graph.node_indices() {
            if let NodeV1::AnswerSummary(summary) = &graph[node_index] {
                answer_summary = Some(summary.clone());
                break; // Assuming there's only one AnswerSummary node in the graph.
            }
        }

        // Iterate through all nodes in the graph to find task nodes.
        for node_index in graph.node_indices() {
            if let NodeV1::Task(task_description) = &graph[node_index] {
                let mut questions = Vec::new();
                let mut answers = Vec::new();
                let mut code_contexts = Vec::new();

                // Logic to collect questions, answers, and code contexts remains the same.

                let merged_code_contexts = merge_code_contexts(&code_contexts);

                tasks_details.push(TaskDetailsWithContext {
                    task_id: node_index.index(),
                    task_description: task_description.clone(),
                    questions,
                    answers,
                    code_contexts,
                    merged_code_contexts,
                });
            }
        }

        // Include the answer summary in the final result if it was found.
        Ok(TasksQuestionsAnswersDetails {
            root_node_id: self.root_node.ok_or(NodeError::RootNodeNotFound)?.index(),
            tasks: tasks_details,
            answer_summary,
        })
    }

    /// Connects the first task in the provided `TasksQuestionsAnswersDetails` to a new `AnswerSummary` node.
    pub fn connect_task_to_answer_summary(
        &mut self,
        task_details: &TasksQuestionsAnswersDetails,
        summary: String,
    ) -> Result<(), NodeError> {
        // Check if the graph is initialized.
        let graph = self.graph.as_mut().ok_or(NodeError::GraphNotInitialized)?;

        if let Some(first_task) = task_details.tasks.first() {
            let task_node_id = NodeIndex::new(first_task.task_id);

            // Find the parent conversation node of the task.
            let parent_conversation_node_id = graph
                .edges_directed(task_node_id, petgraph::Direction::Incoming)
                .find_map(|edge| {
                    if matches!(graph[edge.source()], NodeV1::Conversation(_, _, _)) {
                        Some(edge.source())
                    } else {
                        None
                    }
                })
                .ok_or(NodeError::MissingParentNode)?;

            // Create the AnswerSummary node and connect it to the parent conversation node.
            let answer_summary_node = graph.add_node(NodeV1::AnswerSummary(summary));
            graph.add_edge(
                parent_conversation_node_id,
                answer_summary_node,
                EdgeV1::SummarizedAnswer,
            );
            // save the graph to redis
            if let Err(e) = save_task_process_to_redis(self) {
                error!("Failed to save task process to Redis: {:?}", e);
                // return error if saving to redis fails
                return Err(NodeError::RedisSaveError);
            }
            Ok(())
        } else {
            Err(NodeError::NoTaskFound)
        }
    }
}

pub fn merge_code_contexts(contexts: &Vec<CodeContext>) -> Vec<CodeContext> {
    let mut merged_contexts: Vec<CodeContext> = Vec::new();

    for context in contexts {
        let existing_context = merged_contexts.iter_mut().find(|c| {
            c.path == context.path && c.repo == context.repo && c.branch == context.branch
        });

        match existing_context {
            Some(existing) => {
                existing.ranges.extend(context.ranges.clone());
                existing.ranges = merge_ranges(&existing.ranges.clone());
            }
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
