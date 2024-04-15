use ai_gateway::{config::AIGatewayConfig, function_calling::{Function, FunctionCall}, message::message::Message};
use log::debug;
use anyhow::{Result, anyhow};

pub async fn call_llm(gateway_config: &str, user_msg: Option<String>, history: Option<Vec<Message>>, functions: Option<Vec<Function>>) -> Result<Vec<Message>> {
    let mut ai_gateway_config = AIGatewayConfig::from_yaml(gateway_config)?;
    let result = ai_gateway_config
        .use_llm(user_msg, history, functions)
        .await?;

    debug!("LLM response: {:?}", result);
    Ok(result)
}

/// Function to search through a vector of messages and find the first FunctionCall,
/// returning an Option containing the FunctionCall details and its ID if found.
pub fn find_first_function_call(messages: &[Message]) -> Option<(FunctionCall, Option<String>)> {
    messages.iter().find_map(|message| {
        if let Message::FunctionCall { id, function_call, .. } = message {
            Some((function_call.clone(), id.clone()))
        } else {
            None
        }
    })
}

/// Extracts the content of a PlainText message if it's the only message in the vector.
/// Returns an error if there is more than one message or if the single message is not a PlainText.
pub fn extract_single_plaintext_content(messages: &Vec<Message>) -> Result<String> {
    if messages.len() != 1 {
        return Err(anyhow!("There should be exactly one message in the array."));
    }

    match messages.into_iter().next() {
        Some(Message::PlainText { content, .. }) => Ok(content.clone()),
        Some(_) => Err(anyhow!("The message is not a PlainText message.")),
        None => Err(anyhow!("No message found.")), // This case is technically redundant due to the length check.
    }
}