use crate::models::TaskList;
use crate::task_graph::add_node::NodeError;
use crate::task_graph::graph_model::QuestionWithAnswer;
use crate::task_graph::graph_model::{
    ConversationChain, EdgeV1, NodeV1, QuestionWithId, TrackProcessV1,
};
use crate::task_graph::redis::save_task_process_to_redis;
use anyhow::Result;
use log::{debug, error, info};
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

        // save the task process to redis
        if let Err(e) = save_task_process_to_redis(self) {
            error!("Failed to save task process to Redis: {:?}", e);
            // return error if saving to redis fails
            return Err(NodeError::RedisSaveError);
        }
        info!("Task process saved to Redis after extending graph with conversation and task list");
        Ok(self)
    }

    pub fn integrate_tasks(&mut self, task_list: TaskList) -> Result<&mut Self, NodeError> {
        let _start_node = self
            .last_added_conversation_node
            .ok_or(NodeError::MissingLastUpdatedNode)?;

        if let Some(tasks) = task_list.tasks {
            tasks.into_iter().try_for_each(|task| {
                self.add_task_node(task.task)
                    .and_then(|task_node| {
                        task.subtasks
                            .into_iter()
                            .try_for_each(|subtask| {
                                self.add_subtask_node(subtask.subtask, task_node)
                                    .and_then(|subtask_node| {
                                        subtask.questions.into_iter().try_for_each(
                                            |question_content| {
                                                self.add_question_node(
                                                    question_content,
                                                    subtask_node,
                                                )
                                                .map(|_| ())
                                            },
                                        )
                                    })
                                    .map(|_| ())
                            })
                            .map(|_| ())
                    })
                    .map(|_| ())
            })?;
        }

        Ok(self)
    }

    /// Collects all questions from the graph and returns them as `QuestionWithId`.
    ///
    /// # Returns
    ///
    /// A vector of `QuestionWithId` instances.
    pub fn get_questions_with_ids(&self) -> Vec<QuestionWithId> {
        self.graph.as_ref().map_or_else(Vec::new, |graph| {
            graph
                .node_indices()
                .filter_map(|node_index| {
                    if let Some(NodeV1::Question(text)) = graph.node_weight(node_index) {
                        Some(QuestionWithId {
                            id: node_index.index(),
                            text: text.clone(),
                        })
                    } else {
                        None
                    }
                })
                .collect()
        })
    }

    /// Finds all questions without answers in the graph and returns them along with their NodeIndex.
    pub fn get_unanswered_questions(&self) -> Result<Vec<QuestionWithId>, NodeError> {
        let graph = self.graph.as_ref().ok_or(NodeError::GraphNotInitialized)?;
        let mut unanswered_questions = Vec::new();

        // Iterate over all nodes in the graph.
        for node_index in graph.node_indices() {
            // Check if the node is a Question node.
            if let Some(NodeV1::Question(question)) = graph.node_weight(node_index) {
                // Check if there's no outgoing edge to an Answer node.
                let has_answer = graph
                    .edges_directed(node_index, petgraph::Direction::Outgoing)
                    .any(|edge| matches!(edge.weight(), EdgeV1::Answer));

                // If there's no Answer node connected, add this question to the result.
                if !has_answer {
                    unanswered_questions.push(QuestionWithId {
                        id: node_index.index(),
                        text: question.clone(),
                    });
                }
            }
        }

        Ok(unanswered_questions)
    }

    pub fn extend_graph_with_answers(
        &mut self,
        answers: &Vec<Result<QuestionWithAnswer>>,
    ) -> Result<(), NodeError> {
        // Check if the graph is initialized.
        let graph = self.graph.as_mut().ok_or(NodeError::GraphNotInitialized)?;

        // Iterate through the answers, skipping any that are errors.
        for answer_result in answers {
            if let Ok(answer) = answer_result {
                debug!("Successfully processing an answer: {:?}", answer);
                // Use the NodeIndex from the answer to directly reference the question node.
                let question_node_index = NodeIndex::new(answer.question_id);
                // Ensure the node index points to a valid Question node.
                if let Some(NodeV1::Question(_)) = graph.node_weight(question_node_index) {
                    debug!(
                        "Adding answer to question node with index: {:?}",
                        question_node_index
                    );
                    // Create an Answer node and connect it to the Question node.
                    let answer_node = graph.add_node(NodeV1::Answer(answer.answer.answer.clone()));
                    graph.add_edge(question_node_index, answer_node, EdgeV1::Answer);

                    // Add each CodeContext from the answer as a node connected to the Answer node.
                    for context in answer.answer.context.iter() {
                        let context_node = graph.add_node(NodeV1::CodeContext(context.clone()));
                        graph.add_edge(answer_node, context_node, EdgeV1::CodeContext);
                    }
                } else {
                    return Err(NodeError::InvalidQuestionNode);
                }
            } else {
                error!(
                    "Failed to process an answer due to error: {:?}",
                    answer_result.as_ref().err()
                );
            }
        }
        // update the last_updated timestamp to the current time
        self.last_updated = SystemTime::now();
        // save the task process to redis
        if let Err(e) = save_task_process_to_redis(self) {
            error!("Failed to save task process to Redis: {:?}", e);
            // return error if saving to redis fails
            return Err(NodeError::RedisSaveError);
        }
        Ok(())
    }
}
