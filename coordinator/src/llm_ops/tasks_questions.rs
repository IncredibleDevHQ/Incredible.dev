use crate::utility::call_llm;
use common::models::TaskList;
use common::models::TaskListResponseWithMessage;
use common::prompts;
use log::error;

use ai_gateway::message::message::Message;

pub async fn generate_tasks_and_questions(
    user_query: String,
    repo_name: String,
) -> Result<TaskListResponseWithMessage, anyhow::Error> {
    let system_prompt: String = prompts::question_concept_generator_prompt(&user_query, &repo_name);
    let system_message = Message::system(&system_prompt);
    // append the system message to the message history
    let mut messages = Some(system_message.clone()).into_iter().collect::<Vec<_>>();

    let response_str = call_llm(None, Some(messages.clone())).await.map_err(|e| {
        error!("Failed to start AI Gateway: {:?}", e);
        return e;
    });

    let response = response_str.unwrap();
    // create assistant message and add it to the messages
    let assistant_message = Message::assistant(&response);
    messages.push(assistant_message);

    log::debug!("Choices: {}", response);

    let response_task_list: Result<TaskList, serde_json::Error> = serde_json::from_str(&response);

    match response_task_list {
        Ok(task_list) => {
            //log::debug!("Task list: {:?}", task_list);
            Ok(TaskListResponseWithMessage {
                task_list: task_list,
                messages,
            })
        }
        Err(e) => {
            error!("Failed to parse response from the gateway: {}", e);
            Err(anyhow::anyhow!(
                "Failed to parse response from the gateway: {}",
                e
            ))
        }
    }
}
