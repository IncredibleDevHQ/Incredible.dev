use petgraph::graph::{DiGraph, NodeIndex};
use uuid::Uuid;
use serde::{Serialize, Deserialize};

extern crate common;
use common::models::TaskList;

#[derive(Debug)]
enum Node {
    RootIssue(String, Uuid, ChildTaskStatus),
    Task(String),
    Subtask(String),
    Question(String),
}

#[derive(Debug)]
enum Edge {
    Task,
    Subtask,
    Question,
}

#[derive(Debug)]
enum ChildTaskStatus {
    NotStarted,
    InProgress,
    Done,
}

fn build_graph(task_list: &TaskList, root_issue: &str) -> DiGraph<Node, Edge> {
    let mut graph = DiGraph::<Node, Edge>::new();
    let root_node = graph.add_node(Node::RootIssue(root_issue.to_string(), Uuid::new_v4(), ChildTaskStatus::NotStarted));

    // After processing tasks, you might update the root node status.
    // For simplicity, this example assumes we update it after all tasks are added.
    // In a real scenario, you'd update this based on task completion statuses.

    for task in &task_list.tasks {
        let task_node = graph.add_node(Node::Task(task.task.clone()));
        graph.add_edge(root_node, task_node, Edge::Task);

        for subtask in &task.subtasks {
            let subtask_node = graph.add_node(Node::Subtask(subtask.subtask.clone()));
            graph.add_edge(task_node, subtask_node, Edge::Subtask);

            for question in &subtask.questions {
                let question_node = graph.add_node(Node::Question(question.clone()));
                graph.add_edge(subtask_node, question_node, Edge::Question);
            }
        }
    }

    // Here's a placeholder for updating the root node's status based on tasks.
    // In actual implementation, you should dynamically update this based on task completions.
    // graph[root_node] = Node::RootIssue(root_issue.to_string(), Uuid::new_v4(), ChildTaskStatus::InProgress);

    graph
}
