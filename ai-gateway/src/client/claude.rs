use super::{ClaudeClient, Client, ExtraConfig, Model, PromptType, SendData, TokensCountFactors};
use crate::function_calling::FunctionCall;
use crate::message::message::{Message, MessageRole};

use crate::{render::ReplyHandler, utils::PromptKind};

use anyhow::{anyhow, bail, Result};
use async_trait::async_trait;
use futures_util::StreamExt;
use reqwest::{Client as ReqwestClient, RequestBuilder};
use reqwest_eventsource::{Error as EventSourceError, Event, RequestBuilderExt};
use serde::Deserialize;
use serde_json::{json, Value};

const API_BASE: &str = "https://api.anthropic.com/v1/messages";

const MODELS: [(&str, usize, &str); 3] = [
    // https://docs.anthropic.com/claude/docs/models-overview
    ("claude-3-opus-20240229", 200000, "text,vision"),
    ("claude-3-sonnet-20240229", 200000, "text,vision"),
    ("claude-3-haiku-20240307", 200000, "text,vision"),
];

const TOKENS_COUNT_FACTORS: TokensCountFactors = (5, 2);

#[derive(Debug, Clone, Deserialize)]
pub struct ClaudeConfig {
    pub name: Option<String>,
    pub api_key: Option<String>,
    pub extra: Option<ExtraConfig>,
}

#[async_trait]
impl Client for ClaudeClient {
    client_common_fns!();

    async fn send_message_inner(
        &self,
        client: &ReqwestClient,
        data: SendData,
    ) -> Result<Vec<Message>> {
        let builder = self.request_builder(client, data)?;
        send_message(builder).await
    }

    async fn send_message_streaming_inner(
        &self,
        client: &ReqwestClient,
        handler: &mut ReplyHandler,
        data: SendData,
    ) -> Result<()> {
        let builder = self.request_builder(client, data)?;
        send_message_streaming(builder, handler).await
    }
}

impl ClaudeClient {
    config_get_fn!(api_key, get_api_key);

    pub const PROMPTS: [PromptType<'static>; 1] =
        [("api_key", "API Key:", false, PromptKind::String)];

    pub fn list_models(local_config: &ClaudeConfig) -> Vec<Model> {
        let client_name = Self::name(local_config);
        MODELS
            .into_iter()
            .map(|(name, max_input_tokens, capabilities)| {
                Model::new(client_name, name)
                    .set_capabilities(capabilities.into())
                    .set_max_input_tokens(Some(max_input_tokens))
                    .set_tokens_count_factors(TOKENS_COUNT_FACTORS)
            })
            .collect()
    }

    fn request_builder(&self, client: &ReqwestClient, data: SendData) -> Result<RequestBuilder> {
        let api_key = self.get_api_key().ok();

        let body = build_body(data, self.model.name.clone())?;

        let url = API_BASE;

        log::debug!("Claude Request: {url} {body}");

        let mut builder = client.post(url).json(&body);
        builder = builder.header("anthropic-version", "2023-06-01");
        if let Some(api_key) = api_key {
            builder = builder.header("x-api-key", api_key)
        }

        Ok(builder)
    }
}

/// Sends a request to an API and processes the response to return a collection of Message objects.
/// parses the response 
/// Here is how response for function calling looks like 
/// {
//   "id": "msg_01Aq9w938a90dw8q",
//   "model": "claude-3-opus-20240229",
//   "stop_reason": "tool_use",
//   "role": "assistant",
//   "content": [
//     {
//       "type": "text",
//       "text": "<thinking>I need to call the get_weather function, and the user wants SF, which is likely San Francisco, CA.</thinking>"
//     },
//     {
//       "type": "tool_use",
//       "id": "toolu_01A09q90qw90lq917835lq9", 
//       "name": "get_weather",
//       "input": {"location": "San Francisco, CA", "unit": "celsius"}
//     }
//   ]
// }
pub async fn send_message(builder: RequestBuilder) -> Result<Vec<Message>> {
    let response = builder.send().await?;
    if !response.status().is_success() {
        let error_msg = response.text().await.unwrap_or_default();
        bail!("Request failed: {}", error_msg);
    }

    let data: Value = response.json().await?;
    if let Some(err_msg) = data["error"]["message"].as_str() {
        bail!("API error: {}", err_msg);
    }

    // Initialize an empty vector to store messages
    let mut messages = Vec::new();

    // Process each content entry in the response
    if let Some(contents) = data["content"].as_array() {
        for content in contents {
            let role = MessageRole::Assistant; // Assuming the role is always 'Assistant'
            match content["type"].as_str() {
                Some("text") => {
                    let text = content["text"].as_str().unwrap_or_default();
                    messages.push(Message::PlainText {
                        role,
                        content: text.to_string(),
                    });
                }
                Some("tool_use") => {
                    let id = content["id"].as_str().map(String::from);
                    let function_call = FunctionCall {
                        name: content["name"].as_str().unwrap_or_default().to_string(),
                        arguments: content["input"].to_string(),
                    };
                    messages.push(Message::FunctionCall {
                        id,
                        role,
                        function_call,
                        content: (),
                    });
                }
                _ => continue, // Skip unknown types
            }
        }
    }

    Ok(messages)
}

async fn send_message_streaming(builder: RequestBuilder, handler: &mut ReplyHandler) -> Result<()> {
    let mut es = builder.eventsource()?;
    while let Some(event) = es.next().await {
        match event {
            Ok(Event::Open) => {}
            Ok(Event::Message(message)) => {
                let data: Value = serde_json::from_str(&message.data)?;
                check_error(&data)?;
                if let Some(typ) = data["type"].as_str() {
                    if typ == "content_block_delta" {
                        if let Some(text) = data["delta"]["text"].as_str() {
                            handler.text(text)?;
                        }
                    }
                }
            }
            Err(err) => {
                match err {
                    EventSourceError::StreamEnded => {}
                    EventSourceError::InvalidStatusCode(code, res) => {
                        let data: Value = res.json().await?;
                        check_error(&data)?;
                        bail!("Invalid status code: {code}");
                    }
                    _ => {
                        bail!("{}", err);
                    }
                }
                es.close();
            }
        }
    }

    Ok(())
}

fn build_body(data: SendData, model: String) -> Result<Value> {
    let messages: Vec<Value> = data
        .messages
        .into_iter()
        .map(|message| match message {
            Message::FunctionReturn {
                id,
                role,
                name,
                content,
            } => {
                json!({
                    "role": role,
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": id.unwrap_or_default(),
                        "content": content
                    }]
                })
            }
            Message::FunctionCall {
                id,
                role,
                function_call,
                content: _,
            } => {
                json!({
                    "role": role,
                    "content": [{
                        "type": "tool_use",
                        "id": id,
                        "name": function_call.name,
                        "input": function_call.arguments
                    }]
                })
            }
            Message::PlainText { role, content } => {
                json!({
                    "role": role,
                    "content": content
                })
            }
        })
        .collect();

    let mut body = json!({
        "model": model,
        "messages": messages
    });

    // Optionally add tools, temperature, and stream settings
    if let Some(tools) = data.functions {
        body["tools"] = json!(tools);
    }
    if let Some(v) = data.temperature {
        body["temperature"] = json!(v);
    }
    if data.stream {
        body["stream"] = json!(true);
    }

    Ok(body)
}

fn check_error(data: &Value) -> Result<()> {
    if let Some(error) = data["error"].as_object() {
        if let (Some(typ), Some(message)) = (error["type"].as_str(), error["message"].as_str()) {
            bail!("{typ}: {message}");
        } else {
            bail!("{}", Value::Object(error.clone()))
        }
    }
    Ok(())
}
