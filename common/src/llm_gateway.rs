use anyhow::{Result};
use tiktoken_rs;

use crate::ai_gateway::function_calling::{FunctionCall, Function, Functions};

use serde::{Deserialize, Serialize};

#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct Message {
    pub role: String,
    pub content: Option<String>,
    // add serde macro to make this field optional, so that you ignore if it is not present.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub function_call: Option<FunctionCall>,
}

#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct Choice {
    pub index: usize,
    pub message: Message,
    pub finish_reason: String,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct ChatCompletion {
    pub id: String,
    pub object: String,
    pub created: i64,
    pub model: String,
    pub choices: Vec<Choice>,
    // Include other fields you need here
}

pub mod api {
    use std::collections::HashMap;

    use crate::ai_gateway::function_calling::{Function, FunctionCall};

    #[derive(serde::Serialize, serde::Deserialize, Debug, Clone, PartialEq)]
    #[serde(untagged)]
    pub enum Message {
        FunctionReturn {
            role: String,
            name: String,
            content: String,
        },
        FunctionCall {
            role: String,
            function_call: FunctionCall,
            content: (),
        },
        // NB: This has to be the last variant as this enum is marked `#[serde(untagged)]`, so
        // deserialization will always try this variant last. Otherwise, it is possible to
        // accidentally deserialize a `FunctionReturn` value as `PlainText`.
        PlainText {
            role: String,
            content: String,
        },
    }

    #[derive(serde::Serialize, serde::Deserialize, Debug, Clone)]
    pub enum MessageSource {
        User,
        Assistant,
        System,
    }
    #[derive(serde::Serialize, serde::Deserialize, Debug, Clone)]
    pub struct Messages {
        pub messages: Vec<Message>,
    }

    #[derive(Debug, serde::Serialize, serde::Deserialize)]
    pub struct Request {
        pub messages: Vec<Message>,
        // set rules to ignore the key if the value is None.
        #[serde(skip_serializing_if = "Option::is_none")]
        pub functions: Option<Vec<Function>>,
        //pub provider: Provider,
        //pub max_tokens: Option<u32>,
        //pub temperature: Option<f32>,
        //pub presence_penalty: Option<f32>,
        //pub frequency_penalty: Option<f32>,
        pub model: Option<String>,
        //#[serde(default)]
        //pub extra_stop_sequences: Vec<String>,
        //pub session_reference_id: Option<String>,
    }

    #[derive(Debug, Copy, Clone, serde::Serialize, serde::Deserialize)]
    #[serde(rename_all = "lowercase")]
    pub enum Provider {
        OpenAi,
        Anthropic,
    }

    #[derive(Debug, Copy, Clone, serde::Serialize, serde::Deserialize)]
    #[serde(rename_all = "lowercase")]
    pub enum FunctionCallOptions {
        Auto,
        None,
    }

    #[derive(thiserror::Error, Debug, serde::Deserialize, serde::Serialize)]
    pub enum Error {
        #[error("bad OpenAI request")]
        BadOpenAiRequest,

        #[error("incorrect configuration")]
        BadConfiguration,
    }

    pub type Result = std::result::Result<String, Error>;
}

impl api::Message {
    pub fn new_text(role: &str, content: &str) -> Self {
        Self::PlainText {
            role: role.to_owned(),
            content: content.to_owned(),
        }
    }

    pub fn system(content: &str) -> Self {
        Self::new_text("system", content)
    }

    pub fn user(content: &str) -> Self {
        Self::new_text("user", content)
    }

    pub fn assistant(content: &str) -> Self {
        Self::new_text("assistant", content)
    }

    pub fn function_call(call: &FunctionCall) -> Self {
        Self::FunctionCall {
            role: "assistant".to_string(),
            function_call: call.clone(),
            content: (),
        }
    }

    pub fn function_return(name: &str, content: &str) -> Self {
        Self::FunctionReturn {
            role: "function".to_string(),
            name: name.to_string(),
            content: content.to_string(),
        }
    }
}

impl From<&api::Message> for tiktoken_rs::ChatCompletionRequestMessage {
    fn from(m: &api::Message) -> tiktoken_rs::ChatCompletionRequestMessage {
        match m {
            api::Message::PlainText { role, content } => {
                tiktoken_rs::ChatCompletionRequestMessage {
                    role: role.clone(),
                    content: content.clone(),
                    name: None,
                }
            }
            api::Message::FunctionReturn {
                role,
                name,
                content,
            } => tiktoken_rs::ChatCompletionRequestMessage {
                role: role.clone(),
                content: content.clone(),
                name: Some(name.clone()),
            },
            api::Message::FunctionCall {
                role,
                function_call,
                content: _,
            } => tiktoken_rs::ChatCompletionRequestMessage {
                role: role.clone(),
                content: serde_json::to_string(&function_call).unwrap(),
                name: None,
            },
        }
    }
}

enum ChatError {
    BadRequest,
    TooManyRequests,
    Other(anyhow::Error),
}

#[derive(Clone)]
pub struct Client {
    http: reqwest::Client,
    pub base_url: String,
    pub max_retries: u32,

    pub bearer_token: Option<String>,
    pub temperature: Option<f32>,
    pub max_tokens: Option<u32>,
    pub presence_penalty: Option<f32>,
    pub frequency_penalty: Option<f32>,
    pub provider: api::Provider,
    pub model: Option<String>,
    pub session_reference_id: Option<String>,
}

impl Client {
    pub fn new(base_url: &str) -> Self {
        Self {
            http: reqwest::Client::new(),
            base_url: base_url.to_owned(),
            max_retries: 5,

            bearer_token: None,
            provider: api::Provider::OpenAi,
            temperature: None,
            max_tokens: None,
            presence_penalty: None,
            frequency_penalty: None,
            model: None,
            session_reference_id: None,
        }
    }

    pub fn model(mut self, model: &str) -> Self {
        if model.is_empty() {
            self.model = None;
        } else {
            self.model = Some(model.to_owned());
        }

        self
    }

    pub fn frequency_penalty(mut self, frequency: impl Into<Option<f32>>) -> Self {
        self.frequency_penalty = frequency.into();
        self
    }

    #[allow(unused)]
    pub fn presence_penalty(mut self, presence_penalty: impl Into<Option<f32>>) -> Self {
        self.presence_penalty = presence_penalty.into();
        self
    }

    pub fn temperature(mut self, temperature: impl Into<Option<f32>>) -> Self {
        self.temperature = temperature.into();
        self
    }

    #[allow(unused)]
    pub fn max_tokens(mut self, max_tokens: impl Into<Option<u32>>) -> Self {
        self.max_tokens = max_tokens.into();
        self
    }

    pub fn bearer(mut self, bearer: String) -> Self {
        self.bearer_token = Some(bearer.clone());

        self
    }

    pub fn session_reference_id(mut self, session_reference_id: String) -> Self {
        self.session_reference_id = Some(session_reference_id);
        self
    }

    pub async fn is_compatible(
        &self,
        version: semver::Version,
    ) -> Result<reqwest::Response, reqwest::Error> {
        self.http
            .get(format!("{}/v1/compatibility", self.base_url))
            .query(&[("version", version)])
            .send()
            .await
    }

    pub async fn chat(
        &self,
        messages: &[api::Message],
        functions: Option<&[Function]>,
    ) -> Result<ChatCompletion> {
        // const INITIAL_DELAY: Duration = Duration::from_millis(100);
        // const SCALE_FACTOR: f32 = 1.5;
        println!("llm call");
        match functions {
            Some(_func_call) => {}
            None => {}
        }
        // println!("Messages: \n {:?}", messages);

        let mut builder = self.http.post("https://api.openai.com/v1/chat/completions");
        // set content type application/json
        builder = builder.header("Content-Type", "application/json");
        if let Some(bearer) = &self.bearer_token {
            builder = builder.bearer_auth(bearer);
        }

        // check if functions is None or it has a result.
        if functions.is_none() {
            builder = builder.json(&api::Request {
                messages: messages.to_owned(),
                functions: None,
                //     functions: functions.map(|funcs|
                //  funcs.to_owned(),

                //     ),
                // max_tokens: Some(10000),
                // temperature: Some(0.8),
                // presence_penalty: Some(0.5),
                // frequency_penalty: Some(0.5),
                //provider: self.provider,
                model: self.model.clone(),
                //extra_stop_sequences: vec![],
                //session_reference_id: self.session_reference_id.clone(),
            });
        } else {
            builder = builder.json(&api::Request {
                messages: messages.to_owned(),
                // convert function argument into vector of functions.
                functions: Some(
                    functions
                        .map(|funcs| {
                            Functions {
                                functions: funcs.to_owned(),
                            }
                            .functions
                            .to_owned()
                        })
                        .unwrap(),
                ),
                //     functions: functions.map(|funcs|
                //  funcs.to_owned(),

                //     ),
                // max_tokens: Some(10000),
                // temperature: Some(0.8),
                // presence_penalty: Some(0.5),
                // frequency_penalty: Some(0.5),
                //provider: self.provider,
                model: Some("gpt-4-turbo-preview".to_string()),
                //extra_stop_sequences: vec![],
                //session_reference_id: self.session_reference_id.clone(),
            });
        }
        // use builder to create request
        let request = builder.build();
        if request.is_err() {
            return Err(anyhow::anyhow!("Failed to build request"));
        }
        let request = request.unwrap();
        // call request and await response
        let response = self.http.execute(request).await.map_err(|e| {
            log::debug!("Error: {:?}", e);
            anyhow::anyhow!("Failed to execute request to open AI: {:?}", e)
        })?;

        log::debug!("response status: {:?}", response.status());

        // get response body
        let body = response.text().await?;
        log::debug!("response body from open ai: {:?}\n", body);
    

        // Deserialize the JSON string into a ChatCompletion struct
        let chat_completion: ChatCompletion = serde_json::from_str(&body)?;

        //let result: FunctionCall = chat_completion.choices[0].message.function_call.to_owned();

        Ok(chat_completion)
    }
}
