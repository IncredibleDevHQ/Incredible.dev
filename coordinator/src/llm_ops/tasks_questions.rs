use common::models::TaskListResponseWithMessage;
use common::llm_gateway;
use common::prompts;
use crate::CONFIG;
use crate::controller::suggest::ANSWER_MODEL;
use common::models::TaskList;
use log::error;

pub async fn generate_tasks_and_questions(
    user_query: String,
    repo_name: String,
) -> Result<TaskListResponseWithMessage, anyhow::Error> {
    // initialize new llm gateway.

    // otherwise call the llm gateway to generate the questions
    let llm_gateway = llm_gateway::Client::new(&CONFIG.openai_url)
        .temperature(0.0)
        .bearer(CONFIG.openai_api_key.clone())
        .model(&CONFIG.openai_api_key.clone());

    let system_prompt: String = prompts::question_concept_generator_prompt(&user_query, &repo_name);
    let system_message = llm_gateway::api::Message::system(&system_prompt);
    // append the system message to the message history
    let mut messages = Some(system_message.clone()).into_iter().collect::<Vec<_>>();

    // append the system message to the message history

    let response = match llm_gateway
        .clone()
        .model(ANSWER_MODEL)
        .chat(&messages, None)
        .await
    {
        Ok(response) => Some(response),
        Err(_) => None,
    };
    let final_response = match response {
        Some(response) => response,
        None => {
            log::error!("Error: Unable to fetch response from the gateway");
            // Return error as API response
            return Err(anyhow::anyhow!("Unable to fetch response from the gateway"));
        }
    };

    let choices_str = final_response.choices[0]
        .message
        .content
        .clone()
        .unwrap_or_else(|| "".to_string());

    // create assistant message and add it to the messages
    let assistant_message = llm_gateway::api::Message::assistant(&choices_str);
    messages.push(assistant_message);

    //log::debug!("Choices: {}", choices_str);

    let response_task_list: Result<TaskList, serde_json::Error> =
        serde_json::from_str(&choices_str);

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
