use crate::task_graph::add_node::NodeError;
use crate::task_graph::graph_model::{EdgeV1, NodeV1, TrackProcessV1};
use petgraph::graph::{DiGraph, NodeIndex};
use petgraph::visit::EdgeRef;
use std::fmt;

use std::collections::HashMap;
use std::ops::Range;

use common::CodeContext;
#[derive(Debug, Clone)]
pub struct TasksQuestionsAnswersDetails {
    pub root_node_id: usize,
    pub tasks: Vec<TaskDetailsWithContext>,
}

#[derive(Debug, Clone)]
pub struct AnswerAndContexts {
    pub questions: Vec<String>,
    pub answers: Vec<String>,
    pub code_contexts: Vec<CodeContext>,
    pub merged_code_contexts: Vec<CodeContext>, // Stores the merged contexts
}
#[derive(Debug, Clone)]
pub struct TaskDetailsWithContext {
    pub task_id: usize,
    pub task_description: String,
    pub details: Vec<AnswerAndContexts>,
}

impl TrackProcessV1 {
    // Collects task details along with their associated questions, answers, and code contexts from the graph.
    pub fn collect_tasks_questions_answers_contexts(
        &self,
    ) -> Result<TasksQuestionsAnswersDetails, NodeError> {
        // Check if the graph is initialized.
        let graph = self.graph.as_ref().ok_or(NodeError::GraphNotInitialized)?;
        let mut tasks_details = Vec::new();

        // Iterate through all nodes in the graph to find task nodes.
        for node_index in graph.node_indices() {
            if let NodeV1::Task(task_description) = &graph[node_index] {
                let mut answers_and_contexts = Vec::new();

                // For each task node, find connected subtask nodes and iterate through them.
                for subtask_edge in graph.edges_directed(node_index, petgraph::Direction::Outgoing)
                {
                    if let (NodeV1::Subtask(_), EdgeV1::Subtask) =
                        (&graph[subtask_edge.target()], subtask_edge.weight())
                    {
                        // For each subtask node, find connected question nodes and iterate through them.
                        for question_edge in graph
                            .edges_directed(subtask_edge.target(), petgraph::Direction::Outgoing)
                        {
                            if let (NodeV1::Question(question), EdgeV1::Question) =
                                (&graph[question_edge.target()], question_edge.weight())
                            {
                                let mut answers = Vec::new();
                                let mut code_contexts = Vec::new();

                                // For each question node, find connected answer nodes and collect answers and code contexts.
                                for answer_edge in graph.edges_directed(
                                    question_edge.target(),
                                    petgraph::Direction::Outgoing,
                                ) {
                                    if let NodeV1::Answer(answer) = &graph[answer_edge.target()] {
                                        answers.push(answer.clone());
                                        // For each answer node, find connected code context nodes and collect them.
                                        for context_edge in graph.edges_directed(
                                            answer_edge.target(),
                                            petgraph::Direction::Outgoing,
                                        ) {
                                            if let NodeV1::CodeContext(context) =
                                                &graph[context_edge.target()]
                                            {
                                                code_contexts.push(context.clone());
                                            }
                                        }
                                    }
                                }

                                // Merge overlapping code contexts into a single list.
                                let merged_code_contexts =
                                    merge_code_contexts(code_contexts.clone());

                                // Store the collected question, answers, and contexts together.
                                answers_and_contexts.push(AnswerAndContexts {
                                    questions: vec![question.clone()], // Store the question related to the answers and contexts.
                                    answers,
                                    code_contexts,
                                    merged_code_contexts,
                                });
                            }
                        }
                    }
                }

                // Store the task details along with the collected answers and contexts.
                tasks_details.push(TaskDetailsWithContext {
                    task_id: node_index.index(), // Use the node index as a unique identifier for the task.
                    task_description: task_description.clone(),
                    details: answers_and_contexts,
                });
            }
        }

        // Return the collected task details with their associated questions, answers, and contexts.
        Ok(TasksQuestionsAnswersDetails {
            root_node_id: self.root_node.ok_or(NodeError::RootNodeNotFound)?.index(),
            tasks: tasks_details,
        })
    }
}

fn merge_code_contexts(contexts: Vec<CodeContext>) -> Vec<CodeContext> {
    let mut context_map: HashMap<String, Vec<Range<usize>>> = HashMap::new();

    // Group ranges by file path
    for context in contexts {
        context_map
            .entry(context.path.clone())
            .or_insert_with(Vec::new)
            .extend(context.ranges);
    }

    // Merge ranges for each file path
    context_map.iter_mut().for_each(|(_, ranges)| {
        *ranges = merge_ranges(ranges);
    });

    // Reconstruct CodeContext objects with merged ranges
    context_map
        .into_iter()
        .map(|(path, ranges)| {
            CodeContext {
                path,
                hidden: false,       // Defaulting to false, adjust based on your logic
                repo: String::new(), // Provide actual repo information
                branch: None,        // Provide actual branch information if available
                ranges,
            }
        })
        .collect()
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

impl fmt::Display for AnswerAndContexts {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "Questions:\n")?;
        for question in &self.questions {
            writeln!(f, "- {}", question)?;
        }

        write!(f, "Answers:\n")?;
        for answer in &self.answers {
            writeln!(f, "- {}", answer)?;
        }

        write!(f, "Merged Code Contexts:\n")?;
        for context in &self.merged_code_contexts {
            writeln!(
                f,
                "- Path: {}\n  Hidden: {}\n  Repo: {}\n  Branch: {:?}\n  Ranges: {:?}\n",
                context.path, context.hidden, context.repo, context.branch, context.ranges
            )?;
        }

        Ok(())
    }
}

impl fmt::Display for TaskDetailsWithContext {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        writeln!(
            f,
            "Task ID: {}\nTask Description: {}\n",
            self.task_id, self.task_description
        )?;
        for (i, detail) in self.details.iter().enumerate() {
            writeln!(f, "Detail {}:\n{}", i + 1, detail)?;
        }

        Ok(())
    }
}

impl fmt::Display for TasksQuestionsAnswersDetails {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        writeln!(f, "Root Node ID: {}\n", self.root_node_id)?;
        for (i, task) in self.tasks.iter().enumerate() {
            writeln!(f, "Task {}:\n{}", i + 1, task)?;
        }

        Ok(())
    }
}
