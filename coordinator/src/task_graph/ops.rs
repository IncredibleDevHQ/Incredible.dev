use crate::task_graph::graph_model::{ChildTaskStatus, Edge, Node, QuestionWithId, TrackProcess};

extern crate common;
use common::models::TaskList;
use common::CodeUnderstanding;

impl TrackProcess {
    /// Extends the graph with the structure defined in a TaskList.
    ///
    /// # Arguments
    ///
    /// * `task_list` - A reference to a TaskList containing the tasks, subtasks, and questions
    ///   that will be added to the graph.
    pub fn extend_graph_with_tasklist(&mut self, task_list: &TaskList) {
        // Iterate over each task in the task list.
        task_list.tasks.iter().for_each(|task| {
            // Add each task as a node in the graph and connect it to the root node.
            let task_node = self.graph.add_node(Node::Task(task.task.clone()));
            self.graph.add_edge(self.root_node, task_node, Edge::Task);

            // Use fold to iterate over subtasks, creating nodes and edges, and connecting them to the task node.
            // The task node (task_node_acc) acts as an accumulator that carries forward the node to which
            // subtasks should be connected.
            task.subtasks
                .iter()
                .fold(task_node, |task_node_acc, subtask| {
                    // Add each subtask as a node and connect it to the current task node.
                    let subtask_node = self.graph.add_node(Node::Subtask(subtask.subtask.clone()));
                    self.graph
                        .add_edge(task_node_acc, subtask_node, Edge::Subtask);

                    // Use fold again to iterate over questions for the current subtask.
                    // Here, the subtask node (subtask_node_acc) is the accumulator.
                    subtask
                        .questions
                        .iter()
                        .fold(subtask_node, |subtask_node_acc, question| {
                            self.question_counter += 1;
                            let question_id = self.question_counter;

                            // Create a question node with the ID and the default status.
                            let question_node = self.graph.add_node(Node::Question(
                                question_id,
                                question.clone(),
                                ChildTaskStatus::default(),
                            ));
                            self.graph
                                .add_edge(subtask_node_acc, question_node, Edge::Question);

                            // Return the subtask node accumulator to continue adding questions to the correct subtask.
                            subtask_node_acc
                        });

                    // Return the task node accumulator to continue adding subtasks to the correct task.
                    task_node_acc
                });
        });
    }

    /// Updates the status of the root node in the graph.
    // the status is used to track of the processing of its child nodes
    // in this the child elements are tasks, subtasks and questions
    /// # Arguments
    ///
    /// * `new_status` - The new status to set for the root issue node.
    pub fn update_roots_child_status(&mut self, new_status: ChildTaskStatus) {
        // Match against the root node to extract its current state and update it.
        if let Some(Node::RootIssue(desc, uuid, _)) = self.graph.node_weight_mut(self.root_node) {
            // Update the status of the root node.
            *self.graph.node_weight_mut(self.root_node).unwrap() =
                Node::RootIssue(desc.clone(), *uuid, new_status);
        }
    }

    /// Collects all questions from the graph and returns them as `QuestionWithId`.
    ///
    /// # Returns
    ///
    /// A vector of `QuestionWithId` instances.
    pub fn get_questions_with_ids(&self) -> Vec<QuestionWithId> {
        self.graph
            .node_weights()
            .filter_map(|node| {
                if let Node::Question(id, text, _) = node {
                    Some(QuestionWithId {
                        id: *id,
                        text: text.clone(),
                    })
                } else {
                    None
                }
            })
            .collect()
    }

    pub fn extend_graph_with_answers(&mut self, answers: Vec<(usize, CodeUnderstanding)>) {
        answers.iter().for_each(|(question_id, understanding)| {
            // Find the corresponding question node for the given question_id and update its status to Done.
            if let Some(question_node) = self
                .graph
                .node_indices()
                .find(|&n| matches!(self.graph[n], Node::Question(id, _, _) if id == *question_id))
            {
                // Update the question node's status to Done.
                if let Some(Node::Question(_, _, status)) =
                    self.graph.node_weight_mut(question_node)
                {
                    *status = ChildTaskStatus::Done;
                }

                // Create a node for the answer and connect it to the question node.
                let answer_node = self
                    .graph
                    .add_node(Node::Answer(understanding.answer.clone()));
                self.graph
                    .add_edge(question_node, answer_node, Edge::Answer);

                // Iterate over each CodeContext within the understanding to create and connect nodes.
                understanding.context.iter().for_each(|context| {
                    let context_node = self.graph.add_node(Node::CodeContext(context.clone()));
                    self.graph
                        .add_edge(answer_node, context_node, Edge::CodeContext);
                });
            }
        });
    }
}
