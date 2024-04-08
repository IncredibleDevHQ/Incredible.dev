use super::{
    message::*, Client, ExtraConfig, Model, PromptType, QianwenClient, SendData, TokensCountFactors,
};

use crate::{
    render::ReplyHandler,
    utils::{sha256sum, PromptKind},
};

use anyhow::{anyhow, bail, Context, Result};
use async_trait::async_trait;
use base64::{engine::general_purpose::STANDARD, Engine};
use futures_util::StreamExt;
use reqwest::{
    multipart::{Form, Part},
    Client as ReqwestClient, RequestBuilder,
};
use reqwest_eventsource::{Error as EventSourceError, Event, RequestBuilderExt};
use serde::Deserialize;
use serde_json::{json, Value};
use std::borrow::BorrowMut;

const API_URL: &str =
    "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation";

const API_URL_VL: &str =
    "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation";

const MODELS: [(&str, usize, &str); 4] = [
    // https://help.aliyun.com/zh/dashscope/developer-reference/api-details
    ("qwen-max", 6000, "text"),
    ("qwen-max-longcontext", 28000, "text"),
    ("qwen-plus", 30000, "text"),
    ("qwen-turbo", 6000, "text"),
];

const TOKENS_COUNT_FACTORS: TokensCountFactors = (4, 14);

#[derive(Debug, Clone, Deserialize, Default)]
pub struct QianwenConfig {
    pub name: Option<String>,
    pub api_key: Option<String>,
    pub extra: Option<ExtraConfig>,
}

#[async_trait]
impl Client for QianwenClient {
    client_common_fns!();

    async fn send_message_inner(
        &self,
        client: &ReqwestClient,
        mut data: SendData,
    ) -> Result<String> {
        let api_key = self.get_api_key()?;
        let builder = self.request_builder(client, data)?;
        send_message(builder).await
    }

    async fn send_message_streaming_inner(
        &self,
        client: &ReqwestClient,
        handler: &mut ReplyHandler,
        mut data: SendData,
    ) -> Result<()> {
        let api_key = self.get_api_key()?;
        let builder = self.request_builder(client, data)?;
        send_message_streaming(builder, handler).await
    }
}

impl QianwenClient {
    config_get_fn!(api_key, get_api_key);

    pub const PROMPTS: [PromptType<'static>; 1] =
        [("api_key", "API Key:", true, PromptKind::String)];

    pub fn list_models(local_config: &QianwenConfig) -> Vec<Model> {
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
        let api_key = self.get_api_key()?;

        let stream = data.stream;

        let url = API_URL;
        let (body, has_upload) = build_body(data, self.model.name.clone())?;

        log::debug!("Qianwen Request: {url} {body}");

        let mut builder = client.post(url).bearer_auth(api_key).json(&body);
        if stream {
            builder = builder.header("X-DashScope-SSE", "enable");
        }
        if has_upload {
            builder = builder.header("X-DashScope-OssResourceResolve", "enable");
        }

        Ok(builder)
    }
}

async fn send_message(builder: RequestBuilder) -> Result<String> {
    let data: Value = builder.send().await?.json().await?;
    check_error(&data)?;

    // Extract the "text" directly without checking for VL specific paths.
    let output = data["output"]["text"]
        .as_str()
        .ok_or_else(|| anyhow!("Unexpected response {data}"))?;

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
                // Directly process the message data without checking for VL content.
                if let Some(text) = data["output"]["text"].as_str() {
                    handler.text(text)?;
                }
            }
            Err(err) => {
                match err {
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

fn check_error(data: &Value) -> Result<()> {
    if let (Some(code), Some(message)) = (data["code"].as_str(), data["message"].as_str()) {
        bail!("{code}: {message}");
    }
    Ok(())
}

fn build_body(data: SendData, model: String) -> Result<(Value, bool)> {
    let SendData {
        messages,
        functions,
        temperature,
        stream,
    } = data;

    // Since we're no longer dealing with VL-specific logic, we can streamline the message processing.
    let messages: Vec<Value> = messages
        .into_iter()
        .map(|message| {
            json!({
                "role": message.role,
                "content": message.content,  // Directly use the message content as a string.
            })
        })
        .collect();

    let input = json!({ "messages": messages });

    // Prepare parameters based on the provided temperature and stream settings.
    let mut parameters = json!({});
    if let Some(v) = temperature {
        parameters["temperature"] = v.into();
    }
    if stream {
        parameters["incremental_output"] = true.into();
    }

    // Construct the body with the model, input, and parameters.
    let mut body = json!({
        "model": model,
        "input": input,
        "parameters": parameters
    });

    // Add function calling options if provided.
    if let Some(functions) = functions {
        body["functions"] = json!(functions);
    }

    // The has_upload flag is not used since we don't handle file uploads in this simplified version.
    let has_upload = false;

    Ok((body, has_upload))
}

#[derive(Debug, Deserialize)]
struct Policy {
    data: PolicyData,
}

#[derive(Debug, Deserialize)]
struct PolicyData {
    policy: String,
    signature: String,
    upload_dir: String,
    upload_host: String,
    oss_access_key_id: String,
    x_oss_object_acl: String,
    x_oss_forbid_overwrite: String,
}

/// Upload image to dashscope
async fn upload(model: &str, api_key: &str, url: &str) -> Result<String> {
    let (mime_type, data) = url
        .strip_prefix("data:")
        .and_then(|v| v.split_once(";base64,"))
        .ok_or_else(|| anyhow!("Invalid image url"))?;
    let mut name = sha256sum(data);
    if let Some(ext) = mime_type.strip_prefix("image/") {
        name.push('.');
        name.push_str(ext);
    }
    let data = STANDARD.decode(data)?;

    let client = reqwest::Client::new();
    let policy: Policy = client
        .get(format!(
            "https://dashscope.aliyuncs.com/api/v1/uploads?action=getPolicy&model={model}"
        ))
        .header("Authorization", format!("Bearer {api_key}"))
        .send()
        .await?
        .json()
        .await?;
    let PolicyData {
        policy,
        signature,
        upload_dir,
        upload_host,
        oss_access_key_id,
        x_oss_object_acl,
        x_oss_forbid_overwrite,
        ..
    } = policy.data;

    let key = format!("{upload_dir}/{name}");
    let file = Part::bytes(data).file_name(name).mime_str(mime_type)?;
    let form = Form::new()
        .text("OSSAccessKeyId", oss_access_key_id)
        .text("Signature", signature)
        .text("policy", policy)
        .text("key", key.clone())
        .text("x-oss-object-acl", x_oss_object_acl)
        .text("x-oss-forbid-overwrite", x_oss_forbid_overwrite)
        .text("success_action_status", "200")
        .text("x-oss-content-type", mime_type.to_string())
        .part("file", file);

    let res = client.post(upload_host).multipart(form).send().await?;

    let status = res.status();
    if res.status() != 200 {
        let text = res.text().await?;
        bail!("{status}, {text}")
    }
    Ok(format!("oss://{key}"))
}
