use common::ai_util::extract_single_plaintext_content;
use common::models::TaskList;
use common::models::TaskListResponseWithMessage;
use common::prompts;
use log::error;

use ai_gateway::message::message::Message;
use common::ai_util::call_llm;
use crate::configuration::get_ai_gateway_config;

pub async fn generate_tasks_and_questions(
    user_query: &str,
    repo_name: &str,
) -> Result<TaskListResponseWithMessage, anyhow::Error> {
    let system_prompt: String = prompts::question_concept_generator_prompt(user_query, repo_name);
    let system_message = Message::user(&system_prompt);
    // append the system message to the message history
    let mut messages = Some(system_message.clone()).into_iter().collect::<Vec<_>>();

    let response_messages = call_llm(&get_ai_gateway_config(), None, Some(messages.clone()), None).await?;

    let response = extract_single_plaintext_content(&response_messages)?;
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
