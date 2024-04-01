use common::models::TaskDetailsWithContext;
use common::llm_gateway;
use common::prompts::create_task_answer_summarization_prompt;

use crate::CONFIG;

pub async fn generate_summarized_answer_for_task(
    user_query: String,
    task: TaskDetailsWithContext,
) -> Result<String, anyhow::Error> {
    // Construct the summarization prompt for the given task and user query.
    let summarization_prompt = create_task_answer_summarization_prompt(&user_query, &task);

    // Call the OpenAI API similar to the previous function, using the summarization_prompt.
    let llm_gateway = llm_gateway::Client::new(&CONFIG.openai_url)
        .temperature(0.0)
        .bearer(CONFIG.openai_api_key.clone())
        .model(&CONFIG.openai_api_key.clone());

    let system_message = llm_gateway::api::Message::system(&summarization_prompt);
    let response = llm_gateway
        .clone()
        .chat(&[system_message], None)
        .await
        .map_err(|err| anyhow::anyhow!("Error generating response: {}", err))?;

    let choices_str = response.choices.get(0)
        .and_then(|choice| choice.message.content.as_ref())
        .cloned()
        .unwrap_or_default();

    Ok(choices_str)
}