use crate::task_graph::graph_model::{EdgeV1, NodeV1, QuestionWithId, TrackProcessV1};

use common::llm_gateway::api::{Message, MessageSource};
use common::models::TaskListResponse;
use common::CodeUnderstanding;

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
    pub fn extend_graph_with_tasklist(
        &mut self,
        suggest_response: TaskListResponse,
        system_message: Message,
        assistant_message: Message,
    ) -> bool {
        // Add the system message node connected to the root, representing the system's input or context setup.
        let system_message_node = self.graph.add_node(NodeV1::Conversation(
            MessageSource::System,
            system_message,
            self.uuid,
        ));
        self.graph.add_edge(
            self.root_node,
            system_message_node,
            EdgeV1::NextConversation,
        );

        // Add the assistant message node and connect it to the system message node, representing the assistant's reply.
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

        // If tasks are available in the suggest_response, process them.
        if let Some(tasks) = suggest_response.tasks {
            // Initialize a counter for unique question IDs within this context.
            let mut question_id_counter = 0;

            // Iterate over tasks and integrate them along with their subtasks and questions into the graph.
            tasks.tasks.into_iter().for_each(|task| {
                let task_node = self.graph.add_node(NodeV1::Task(task.task));
                self.graph
                    .add_edge(assistant_message_node, task_node, EdgeV1::Process);

                task.subtasks.into_iter().for_each(|subtask| {
                    let subtask_node = self.graph.add_node(NodeV1::Subtask(subtask.subtask));
                    self.graph
                        .add_edge(task_node, subtask_node, EdgeV1::Subtask);

                    subtask.questions.into_iter().for_each(|question| {
                        let question_node = self.graph.add_node(NodeV1::Question(
                            question_id_counter, // Use the counter as the question ID.
                            question,
                        ));
                        self.graph
                            .add_edge(subtask_node, question_node, EdgeV1::Question);
                        question_id_counter += 1; // Increment the counter for the next question.
                    });
                });
            });

            return true;
        }
        false
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
