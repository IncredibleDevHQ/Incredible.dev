
use crate::task_graph::graph_model::{TrackProcess, Node, Edge};

extern crate common;
use common::models::TaskList;

impl TrackProcess {
    /// Extends the graph with the structure defined in a TaskList.
    /// 
    /// # Arguments
    /// 
    /// * `task_list` - A reference to a TaskList containing the tasks, subtasks, and questions
    ///   that will be added to the graph.
    fn extend_graph_with_tasklist(&mut self, task_list: &TaskList) {
        // Iterate over each task in the task list.
        task_list.tasks.iter().for_each(|task| {
            // Add each task as a node in the graph and connect it to the root node.
            let task_node = self.graph.add_node(Node::Task(task.task.clone()));
            self.graph.add_edge(self.root_node, task_node, Edge::Task);

            // Use fold to iterate over subtasks, creating nodes and edges, and connecting them to the task node.
            // The task node (task_node_acc) acts as an accumulator that carries forward the node to which
            // subtasks should be connected.
            task.subtasks.iter().fold(task_node, |task_node_acc, subtask| {
                // Add each subtask as a node and connect it to the current task node.
                let subtask_node = self.graph.add_node(Node::Subtask(subtask.subtask.clone()));
                self.graph.add_edge(task_node_acc, subtask_node, Edge::Subtask);

                // Use fold again to iterate over questions for the current subtask.
                // Here, the subtask node (subtask_node_acc) is the accumulator.
                subtask.questions.iter().fold(subtask_node, |subtask_node_acc, question| {
                    // Add each question as a node and connect it to the current subtask node.
                    let question_node = self.graph.add_node(Node::Question(question.clone()));
                    self.graph.add_edge(subtask_node_acc, question_node, Edge::Question);

                    // Return the subtask node accumulator to continue adding questions to the correct subtask.
                    subtask_node_acc
                });

                // Return the task node accumulator to continue adding subtasks to the correct task.
                task_node_acc
            });
        });
    }
}