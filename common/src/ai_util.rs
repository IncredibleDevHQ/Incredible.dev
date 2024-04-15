use ai_gateway::{config::AIGatewayConfig, function_calling::FunctionCall, message::message::Message};
use log::debug;
use anyhow::Result;

pub async fn call_llm(gateway_config: &str, user_msg: Option<String>, history: Option<Vec<Message>>) -> Result<Vec<Message>> {
    let mut ai_gateway_config = AIGatewayConfig::from_yaml(gateway_config)?;
    let result = ai_gateway_config
        .use_llm(user_msg, history, None)
        .await?;

    debug!("LLM response: {:?}", result);
    Ok(result)
}

/// Function to search through a vector of messages and find the first FunctionCall,
/// returning an Option containing the FunctionCall details and its ID if found.
fn find_first_function_call(messages: &[Message]) -> Option<(FunctionCall, Option<String>)> {
    messages.iter().find_map(|message| {
        if let Message::FunctionCall { id, function_call, .. } = message {
            Some((function_call.clone(), id.clone()))
        } else {
            None
        }
    })
}