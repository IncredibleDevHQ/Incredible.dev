use log::debug;

use crate::controller::suggest::ANSWER_MODEL;
use common::llm_gateway;
use common::models::TasksQuestionsAnswersDetails;
use common::prompts::create_task_answer_summarization_prompt;

use crate::CONFIG;

pub async fn generate_summarized_answer_for_task(
    user_query: String,
    task: &TasksQuestionsAnswersDetails,
) -> Result<String, anyhow::Error> {
    // Construct the summarization prompt for the given task and user query.
    let summarization_prompt = create_task_answer_summarization_prompt(&user_query, &task);

    debug!("Summarization prompt: {}", summarization_prompt);

    let llm_gateway = llm_gateway::Client::new(&CONFIG.openai_url)
        .temperature(0.0)
        .bearer(CONFIG.openai_api_key.clone())
        .model(&CONFIG.openai_api_key.clone());
    let system_message = llm_gateway::api::Message::system(&summarization_prompt);
    // append the system message to the message history
    let mut messages = Some(system_message.clone()).into_iter().collect::<Vec<_>>();

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

    debug!("Summarized answer: {}", choices_str);
    Ok(choices_str)
}
