use super::{ClaudeClient, Client, ExtraConfig, Model, PromptType, SendData, TokensCountFactors};
use crate::message::message::Message;

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

    async fn send_message_inner(&self, client: &ReqwestClient, data: SendData) -> Result<String> {
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

async fn send_message(builder: RequestBuilder) -> Result<String> {
    let data: Value = builder.send().await?.json().await?;
    check_error(&data)?;

    let output = data["content"][0]["text"]
        .as_str()
        .ok_or_else(|| anyhow!("Invalid response data: {data}"))?;

    Ok(output.to_string())
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
    let SendData {
        messages,
        functions,
        temperature,
        stream,
    } = data;

    // Serialize messages with content being just a string without specifying the type.
    let messages: Vec<Value> = messages
        .into_iter()
        .map(|message| match message {
            Message::FunctionReturn {
                role,
                name,
                content,
            } => {
                json!({
                    "role": role,
                    "type": "function_return",
                    "name": name,
                    "content": content
                })
            }
            Message::FunctionCall {
                role,
                function_call,
                content: _,
            } => {
                json!({
                    "role": role,
                    "type": "function_call",
                    "function_call": function_call
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
        "max_tokens": 4096,
        "messages": messages,
    });

    // Add functions (tools in Anthropics terminology) if available.
    // https://docs.anthropic.com/claude/docs/tool-use
    if let Some(tools) = functions {
        body["tools"] = json!(tools);
    }

    // Add temperature and stream settings if they are present.
    if let Some(v) = temperature {
        body["temperature"] = json!(v);
    }
    if stream {
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