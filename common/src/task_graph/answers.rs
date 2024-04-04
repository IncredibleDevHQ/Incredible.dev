use std::ops::Range;

use crate::task_graph::add_node::NodeError;
use crate::task_graph::graph_model::{EdgeV1, NodeV1, TrackProcessV1};
use crate::task_graph::redis::save_task_process_to_redis;

use petgraph::graph::{DiGraph, NodeIndex, EdgeIndex};
use petgraph::visit::EdgeRef;
use petgraph::Direction;


use crate::models::{TaskDetailsWithContext, TasksQuestionsAnswersDetails};
use crate::CodeContext;

use log::{error, debug};

impl TrackProcessV1 {
    /// Collects details about tasks, questions, answers, and code contexts from the graph.
    /// Additionally, it checks for an answer summary in the graph and includes it if present.
    pub fn collect_tasks_questions_answers_contexts(
        &self,
    ) -> Result<TasksQuestionsAnswersDetails, NodeError> {
        // Ensure the graph is initialized before proceeding.
        let graph = self.graph.as_ref().ok_or(NodeError::GraphNotInitialized)?;
        let mut tasks_details = Vec::new();
        let mut answer_summary: Option<String> = None;

        // Iterate through all nodes in the graph to process tasks and check for an answer summary.
        for node_index in graph.node_indices() {
            match &graph[node_index] {
                // If the current node is a task, collect its related details.
                NodeV1::Task(task_description) => {
                    let task_details =
                        self.collect_task_details(graph, node_index, task_description)?;
                    tasks_details.push(task_details);
                }
                // If an answer summary node is found, store its content.
                NodeV1::AnswerSummary(summary) => {
                    answer_summary = Some(summary.clone());
                }
                // Ignore other node types.
                _ => {}
            }
        }

        // Return the aggregated details including tasks and potential answer summary.
        Ok(TasksQuestionsAnswersDetails {
            root_node_id: self.root_node.ok_or(NodeError::RootNodeNotFound)?.index(),
            tasks: tasks_details,
            answer_summary,
        })
    }

    /// Collects details for a specific task including its questions, answers, and code contexts.
    fn collect_task_details(
        &self,
        graph: &DiGraph<NodeV1, EdgeV1>,
        node_index: NodeIndex,
        task_description: &String,
    ) -> Result<TaskDetailsWithContext, NodeError> {
        let mut questions = Vec::new();
        let mut answers = Vec::new();
        let mut code_contexts = Vec::new();

        // For the given task node, iterate over its connected subtask nodes.
        for edge in graph.edges_directed(node_index, Direction::Outgoing) {
            if let NodeV1::Subtask(_) = &graph[edge.target()] {
                // For each subtask node, collect its connected questions.
                for subtask_edge in graph.edges_directed(edge.target(), Direction::Outgoing) {
                    if let NodeV1::Question(question) = &graph[subtask_edge.target()] {
                        questions.push(question.clone());
                        // Collect answers and code contexts for each question.
                        self.collect_answers_and_contexts(
                            graph,
                            subtask_edge.target(),
                            &mut answers,
                            &mut code_contexts,
                        )?;
                    }
                }
            }
        }

        // Merge overlapping code contexts to ensure there are no redundant entries.
        let merged_code_contexts = merge_code_contexts(&code_contexts);

        // Return the aggregated details for the task including its questions, answers, and code contexts.
        Ok(TaskDetailsWithContext {
            task_id: node_index.index(), // Use the node index as a unique identifier for the task.
            task_description: task_description.clone(),
            questions,
            answers,
            code_contexts,
            merged_code_contexts,
        })
    }

    /// Collects answers and code contexts connected to a given question node.
    fn collect_answers_and_contexts(
        &self,
        graph: &DiGraph<NodeV1, EdgeV1>,
        question_node: NodeIndex,
        answers: &mut Vec<String>,
        code_contexts: &mut Vec<CodeContext>,
    ) -> Result<(), NodeError> {
        // Iterate over edges from the question node to find connected answer nodes.
        for answer_edge in graph.edges_directed(question_node, Direction::Outgoing) {
            if let NodeV1::Answer(answer) = &graph[answer_edge.target()] {
                answers.push(answer.clone());
                // For each answer node, collect connected code context nodes.
                for context_edge in graph.edges_directed(answer_edge.target(), Direction::Outgoing)
                {
                    if let NodeV1::CodeContext(context) = &graph[context_edge.target()] {
                        code_contexts.push(context.clone());
                    }
                }
            }
        }
        Ok(())
    }
    /// Connects the first task in the provided `TasksQuestionsAnswersDetails` to a new `AnswerSummary` node,
    /// ensuring there's only one summary node per task by removing any existing summary nodes.
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

            // Check for an existing summary node and remove it along with its edge before adding a new one.
            let existing_summary_edges: Vec<EdgeIndex> = graph
                .edges_directed(parent_conversation_node_id, petgraph::Direction::Outgoing)
                .filter(|edge| matches!(graph[edge.target()], NodeV1::AnswerSummary(_)))
                .map(|edge| edge.id())
                .collect();

            for edge_id in existing_summary_edges {
                debug!("Removing existing summary edge: {:?}", edge_id);
                graph.remove_edge(edge_id);
            }

            // Once existing summaries are cleared, add the new AnswerSummary node.
            let answer_summary_node = graph.add_node(NodeV1::AnswerSummary(summary));
            graph.add_edge(
                parent_conversation_node_id,
                answer_summary_node,
                EdgeV1::SummarizedAnswer,
            );

            // Attempt to save the updated graph to Redis.
            save_task_process_to_redis(self).map_err(|e| {
                error!("Failed to save task process to Redis: {:?}", e);
                NodeError::RedisSaveError
            })
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
