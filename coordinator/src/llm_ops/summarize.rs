use common::ai_util::{call_llm, extract_single_plaintext_content};
use log::debug;

use common::models::TasksQuestionsAnswersDetails;
use common::prompts::create_task_answer_summarization_prompt;

use crate::configuration::get_ai_gateway_config;

pub async fn generate_summarized_answer_for_task(
    user_query: String,
    task: &TasksQuestionsAnswersDetails,
) -> Result<String, anyhow::Error> {
    // Construct the summarization prompt for the given task and user query.
    let summarization_prompt = create_task_answer_summarization_prompt(&user_query, &task);

    //debug!("Summarization prompt: {}", summarization_prompt);

    let llm_output = call_llm(&get_ai_gateway_config(), Some(summarization_prompt), None, None).await?;

    let response_message = extract_single_plaintext_content(&llm_output)?;
    debug!("Summarized answer: {}", response_message);
    Ok(response_message)
}

// pub async fn generate_single_task_summarization_(
//     user_query: &str,
//     search_url: &str,
//     task: &TaskDetailsWithContext,
// ) -> Result<String, anyhow::Error> {
//     let open_ai_url = get_openai_url();
//     let open_ai_model = get_openai_model();
//     let open_ai_key = get_openai_api_key();
//     // Construct the summarization prompt for the given task and user query.
//     let summarization_prompt =
//         generate_single_task_summarization_prompt(user_query, search_url, task).await?;

//     //debug!("Summarization prompt: {}", summarization_prompt);

//     let llm_gateway = llm_gateway::Client::new(&open_ai_url)
//         .temperature(0.0)
//         .bearer(open_ai_key)
//         .model(&open_ai_model);
//     let system_message = message::Message::system(&summarization_prompt);
//     // append the system message to the message history
//     let messages = Some(system_message.clone()).into_iter().collect::<Vec<_>>();

//     let response = match llm_gateway
//         .clone()
//         .model(&open_ai_model)
//         .chat(&messages, None)
//         .await
//     {
//         Ok(response) => Ok(response),
//         Err(e) => {
//             log::error!("Error: Unable to fetch response from the gateway: {:?}", e);
//             Err(anyhow::anyhow!("Unable to fetch response from the gateway"))
//         }
//     };
//     let final_response = match response {
//         Ok(response) => response,
//         Err(e) => {
//             log::error!("Error: Unable to fetch response from the gateway: {:?}", e);
//             // Return error as API response
//             return Err(anyhow::anyhow!(
//                 "Unable to fetch response from the gateway: {:?}",
//                 e
//             ));
//         }
//     };

//     let choices_str = final_response.choices[0]
//         .message
//         .content
//         .clone()
//         .unwrap_or_else(|| "".to_string());

//     debug!("Summarized answer: {}", choices_str);
//     Ok(choices_str)
// }
