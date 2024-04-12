use super::{ExtraConfig, Model, OpenAIClient, PromptType, SendData, TokensCountFactors};

use crate::{function_calling::FunctionCall, message::message::MessageRole, render::ReplyHandler, utils::PromptKind};

use anyhow::{anyhow, bail, Result};
use async_trait::async_trait;
use futures_util::StreamExt;
use reqwest::{Client as ReqwestClient, RequestBuilder};
use reqwest_eventsource::{Error as EventSourceError, Event, RequestBuilderExt};
use serde::Deserialize;
use serde_json::{json, Value};

const API_BASE: &str = "https://api.openai.com/v1";

const MODELS: [(&str, usize, &str); 5] = [
    // https://platform.openai.com/docs/models/gpt-4-and-gpt-4-turbo
    ("gpt-4-turbo-preview", 128000, "text"),
    ("gpt-4-vision-preview", 128000, "text,vision"),
    ("gpt-4-1106-preview", 128000, "text"),
    // https://platform.openai.com/docs/models/gpt-3-5-turbo
    ("gpt-3.5-turbo", 16385, "text"),
    ("gpt-3.5-turbo-1106", 16385, "text"),
];

pub const OPENAI_TOKENS_COUNT_FACTORS: TokensCountFactors = (5, 2);

#[derive(Debug, Clone, Deserialize, Default)]
pub struct OpenAIConfig {
    pub name: Option<String>,
    pub api_key: Option<String>,
    pub api_base: Option<String>,
    pub organization_id: Option<String>,
    pub extra: Option<ExtraConfig>,
}

openai_compatible_client!(OpenAIClient);

impl OpenAIClient {
    config_get_fn!(api_key, get_api_key);
    config_get_fn!(api_base, get_api_base);

    pub const PROMPTS: [PromptType<'static>; 1] =
        [("api_key", "API Key:", true, PromptKind::String)];

    pub fn list_models(local_config: &OpenAIConfig) -> Vec<Model> {
        let client_name = Self::name(local_config);
        MODELS
            .into_iter()
            .map(|(name, max_input_tokens, capabilities)| {
                Model::new(client_name, name)
                    .set_capabilities(capabilities.into())
                    .set_max_input_tokens(Some(max_input_tokens))
                    .set_tokens_count_factors(OPENAI_TOKENS_COUNT_FACTORS)
            })
            .collect()
    }

    fn request_builder(&self, client: &ReqwestClient, data: SendData) -> Result<RequestBuilder> {
        let api_key = self.get_api_key()?;
        let api_base = self.get_api_base().unwrap_or_else(|_| API_BASE.to_string());

        let body = openai_build_body(data, self.model.name.clone());

        let url = format!("{api_base}/chat/completions");

        log::debug!("OpenAI Request: {url} {body}");

        let mut builder = client.post(url).bearer_auth(api_key).json(&body);

        if let Some(organization_id) = &self.config.organization_id {
            builder = builder.header("OpenAI-Organization", organization_id);
        }

        Ok(builder)
    }
}

pub async fn openai_send_message(builder: RequestBuilder) -> Result<Message> {
    let response = builder.send().await?;
    if !response.status().is_success() {
        let error_msg = response.text().await.unwrap_or_default();
        bail!("Request failed: {error_msg}");
    }

    let data: Value = response.json().await?;
    if let Some(err_msg) = data["error"]["message"].as_str() {
        bail!("{err_msg}");
    }

    let choices = data["choices"][0].clone();
    // 
    let role = MessageRole::Assistant; 

    if choices["finish_reason"] == "tool_calls" {
        let tool_calls = &choices["message"]["tool_calls"];
        if tool_calls.is_array() && !tool_calls[0].is_null() {
            let tool_call = &tool_calls[0];
            let id = tool_call["id"].as_str().map(String::from);
            let function = &tool_call["function"];
            let name = function["name"].as_str().map(String::from);
            let arguments = function["arguments"]
                .as_str()
                .unwrap_or_default()
                .to_string();

            Ok(Message::FunctionCall {
                id,
                role,
                function_call: FunctionCall { name, arguments },
                content: (),
            })
        } else {
            bail!("No valid tool calls found in the response");
        }
    } else {
        let content = choices["message"]["content"]
            .as_str()
            .ok_or_else(|| anyhow!("Invalid response data: {data}"))?
            .to_string();

        Ok(Message::PlainText { role, content })
    }
}

pub async fn openai_send_message_streaming(
    builder: RequestBuilder,
    handler: &mut ReplyHandler,
) -> Result<()> {
    let mut es = builder.eventsource()?;
    while let Some(event) = es.next().await {
        match event {
            Ok(Event::Open) => {}
            Ok(Event::Message(message)) => {
                if message.data == "[DONE]" {
                    break;
                }
                let data: Value = serde_json::from_str(&message.data)?;
                if let Some(text) = data["choices"][0]["delta"]["content"].as_str() {
                    handler.text(text)?;
                }
            }
            Err(err) => {
                match err {
                    EventSourceError::InvalidStatusCode(_, res) => {
                        let data: Value = res.json().await?;
                        if let Some(err_msg) = data["error"]["message"].as_str() {
                            bail!("{err_msg}");
                        } else if let Some(err_msg) = data["message"].as_str() {
                            bail!("{err_msg}");
                        } else {
                            bail!("Request failed, {data}");
                        }
                    }
                    EventSourceError::StreamEnded => {}
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

pub fn openai_build_body(data: SendData, model: String) -> Value {
    let SendData {
        messages,
        functions,
        temperature,
        stream,
    } = data;

    let mut body = json!({
        "model": model,
        "messages": messages,
    });

    // Check if there are any functions provided and add them to the body.
    if let Some(funcs) = functions {
        // Here we assume that the functions Vec<Function> can be serialized directly.
        // This requires that Function and any nested structs are serializable.
        body["functions"] = json!(funcs);
    }

    // The default max_tokens of gpt-4-vision-preview is only 16, we need to make it larger
    if model == "gpt-4-vision-preview" {
        body["max_tokens"] = json!(4096);
    }

    if let Some(v) = temperature {
        body["temperature"] = v.into();
    }
    if stream {
        body["stream"] = true.into();
    }
    body
}
