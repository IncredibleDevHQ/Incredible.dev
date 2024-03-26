use crate::task_graph::graph_model::{
    ConversationChain, EdgeV1, NodeV1, QuestionWithId, TrackProcessV1,
};
use crate::task_graph::add_node::NodeError;
use crate::task_graph::redis::{load_task_process_from_redis, save_task_process_to_redis};
use anyhow::Result;
use common::llm_gateway::api::{Message, MessageSource};
use common::models::TaskList;
use common::CodeUnderstanding;
use log::error;
use petgraph::graph::NodeIndex;
use std::time::SystemTime;

impl TrackProcessV1 {
    /// Extends the graph with a chain of conversation nodes followed by task-related nodes if a task list is provided.
///
/// # Arguments
///
/// * `conversation_chain` - A struct containing the user, system, and assistant messages to be added as conversation nodes in sequence.
/// * `task_list` - An optional `TaskList` containing tasks, subtasks, and questions to be integrated into the graph following the conversation nodes.
///
/// # Returns
/// * `&mut Self` - A mutable reference to the instance for chaining further method calls.
/// * `NodeError` - An error if the operation fails, such as when an invalid node ID is encountered.
///
/// # Graph Structure
/// Here's how the graph looks after processing the conversation chain and optional task list:
/// ```
/// Root Node: Conversation (Root)
/// │
/// ├── NextConversation Edge
/// │   │
/// │   └── Conversation Node: User (User message)
/// │       │
/// │       ├── NextConversation Edge
/// │       │   │
/// │       │   └── Conversation Node: System (System message)
/// │       │       │
/// │       │       ├── NextConversation Edge
/// │       │       │   │
/// │       │       │   └── Conversation Node: Assistant (Assistant message)
/// │       │       │       │
/// │       │       │       └── Process Edge (only if a task list is present)
/// │       │       │           │
/// │       │       │           └── Task Node (First task from the task list)
/// │       │       │               │
/// │       │       │               ├── Subtask Edge
/// │       │       │               │   │
/// │       │       │               │   └── Subtask Node (First subtask of the task)
/// │       │       │               │       │
/// │       │       │               │       └── Question Edge
/// │       │       │               │           │
/// │       │       │               │           └── Question Node (First question of the subtask)
/// │       │       │               │
/// │       │       │               └── (Additional Subtask and Question Nodes as needed)
/// │       │       │
/// │       │       └── (Additional Task Nodes and their structures as needed)
/// │       │
/// │       └── (Additional Conversation Nodes for ongoing dialogue)
/// │
/// └── (The graph continues to expand with more nodes and edges as the conversation and task processing evolve)
/// ```

    pub fn extend_graph_with_conversation_and_tasklist(
        &mut self,
        conversation_chain: ConversationChain,
        task_list: Option<TaskList>,
    ) -> Result<&mut Self, NodeError> {
        // Initialize the graph and root node if they don't exist.
        if self.graph.is_none() {
            self.initialize_graph();
        }

        // Add the user, system, and assistant messages as conversation nodes, chaining each to the last.
        self.add_user_conversation(conversation_chain.user_message)?
            .add_system_conversation(conversation_chain.system_message)?
            .add_assistant_conversation(conversation_chain.assistant_message)?;

        // If a task list is provided, integrate it into the graph.
        if let Some(tasks) = task_list {
            self.integrate_tasks(tasks)?;
        }

        // Update the last_updated timestamp to the current time.
        self.last_updated = SystemTime::now();

        Ok(self)
    }

    fn integrate_tasks(&mut self, tasks: TaskList) -> Result<&mut Self, NodeError> {
        // Ensure we're starting from the assistant message node.
        let start_node = self
            .last_added_conversation_node
            .ok_or(NodeError::MissingLastUpdatedNode)?;

        // Use flat_map to process each task, its subtasks, and questions in a flattened iterator.
        tasks
            .tasks
            .into_iter()
            .flat_map(|task| {
                let task_node = self.add_task_node(task.task)?;

                task.subtasks.into_iter().flat_map(move |subtask| {
                    let subtask_node = self.add_subtask_node(subtask.subtask, task_node)?;

                    subtask
                        .questions
                        .into_iter()
                        .map(move |question| self.add_question_node(question, subtask_node))
                })
            })
            .collect::<Result<Vec<_>, _>>()?;

        Ok(self)
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
                if let NodeV1::Question(id, text) = node {
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
                .find(|&n| matches!(self.graph[n], NodeV1::Question(id, _) if id == *question_id))
            {
                // Create a node for the answer and connect it to the question node.
                let answer_node = self
                    .graph
                    .add_node(NodeV1::Answer(understanding.answer.clone()));
                self.graph
                    .add_edge(question_node, answer_node, EdgeV1::Answer);

                // Iterate over each CodeContext within the understanding to create and connect nodes.
                understanding.context.iter().for_each(|context| {
                    let context_node = self.graph.add_node(NodeV1::CodeContext(context.clone()));
                    self.graph
                        .add_edge(answer_node, context_node, EdgeV1::CodeContext);
                });
            }
        });
    }
}
