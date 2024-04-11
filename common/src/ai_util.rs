use ai_gateway::{config::AIGatewayConfig, message::message::Message};
use log::debug;
use anyhow::Result;

pub async fn call_llm(gateway_config: &str, user_msg: Option<String>, history: Option<Vec<Message>>) -> Result<String> {
    let mut ai_gateway_config = AIGatewayConfig::from_yaml(gateway_config)?;
    let result = ai_gateway_config
        .use_llm(user_msg, history, None, true, false)
        .await?;

    debug!("LLM response: {}", result);
    Ok(result)
}