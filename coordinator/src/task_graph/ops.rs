use crate::task_graph::graph_model::{EdgeV1, NodeV1, QuestionWithId, TrackProcessV1};
use crate::task_graph::redis::{load_task_process_from_redis, save_task_process_to_redis};
use anyhow::Result;
use common::llm_gateway::api::{Message, MessageSource};
use common::models::TaskListResponse;
use common::CodeUnderstanding;
use log::error;
use petgraph::graph::NodeIndex;


impl TrackProcessV1 {
    /// Processes the suggestion response by integrating tasks, subtasks, and questions into the graph.
    ///
    /// # Arguments
    ///
    /// * `suggest_response` - The response from the suggestion API containing tasks or message asking users for further information.
    /// * `system_message` - The system message, typically a prompt or an informational message.
    /// * `assistant_message` - The assistant's response, which could be an action item or further query.
    /// # Returns
    /// a bool indicating if tasks are available in the suggest_response
    ///
    /// here's how the graph looks like
    /// Root Node: Conversation (Root)
    // │
    // ├── NextConversation Edge
    // │   │
    // │   └── Conversation Node: System (System message)
    // │       │
    // │       ├── NextConversation Edge
    // │       │   │
    // │       │   └── Conversation Node: Assistant (Assistant message)
    // │       │       │
    // │       │       └── Process Edge (only if tasks are present)
    // │       │           │
    // │       │           └── Task Node
    // │       │               │
    // │       │               ├── Subtask Edge
    // │       │               │   │
    // │       │               │   └── Subtask Node
    // │       │               │       │
    // │       │               │       └── Question Edge
    // │       │               │           │
    // │       │               │           └── Question Node
    // │       │               │               │ (Future implementation might connect to Answer and CodeContext Nodes)
    // │       │               │
    // │       │               └── (Additional Subtask Nodes and their Question Nodes as needed)
    // │       │
    // │       └── (Additional Task Nodes and their Subtask/Question structures as needed)
    // │
    // └── (Future Conversation Nodes connected via NextConversation Edges as the chat progresses)

    pub fn extend_graph_with_tasklist(
        &mut self,
        suggest_response: TaskListResponse,
        system_message: Message,
        assistant_message: Message,
        base_node_id: Option<NodeIndex>, // Add this parameter to accept an optional base node ID.
    ) -> Result<bool> {
        // Determine the base node for attaching the system and assistant messages.
        let base_node = base_node_id
            .and_then(|node_id| {
                // Validate if the provided node ID is a conversation node.
                match self.graph.node_weight(node_id) {
                    Some(NodeV1::Conversation(..)) => Some(node_id),
                    _ => None,
                }
            })
            .unwrap_or(self.root_node);
    
        // Add the system message node connected to the base node.
        let system_message_node = self.graph.add_node(NodeV1::Conversation(
            MessageSource::System,
            system_message,
            self.uuid,
        ));
        self.graph.add_edge(base_node, system_message_node, EdgeV1::NextConversation);
    
        // Add the assistant message node and connect it to the system message node.
        let assistant_message_node = self.graph.add_node(NodeV1::Conversation(
            MessageSource::Assistant,
            assistant_message,
            self.uuid,
        ));
        self.graph.add_edge(
            system_message_node,
            assistant_message_node,
            EdgeV1::NextConversation,
        );
    
        // Process the tasks and subtasks if they are present.
        if let Some(tasks) = suggest_response.tasks {
            let mut question_id_counter = 0;
            tasks.tasks.into_iter().for_each(|task| {
                let task_node = self.graph.add_node(NodeV1::Task(task.task));
                self.graph.add_edge(assistant_message_node, task_node, EdgeV1::Process);
    
                task.subtasks.into_iter().for_each(|subtask| {
                    let subtask_node = self.graph.add_node(NodeV1::Subtask(subtask.subtask));
                    self.graph.add_edge(task_node, subtask_node, EdgeV1::Subtask);
    
                    subtask.questions.into_iter().for_each(|question| {
                        let question_node = self.graph.add_node(NodeV1::Question(
                            question_id_counter,
                            question,
                        ));
                        self.graph.add_edge(subtask_node, question_node, EdgeV1::Question);
                        question_id_counter += 1;
                    });
                });
            });
    
            // Save the graph in Redis.
            let redis_result = save_task_process_to_redis(self);
            if redis_result.is_err() {
                error!(
                    "Failed to save task process with tasks to Redis: {:?}",
                    redis_result.err().unwrap()
                );
                return Err(redis_result.err().unwrap());
            }
            return Ok(true);
        }
    
        // If no tasks were processed, indicate that with a return value.
        Ok(false)
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
