use crate::ai_gateway::client::{list_models, ClientConfig, Model, SendData, Message};
use crate::ai_gateway::render::RenderOptions;
use crate::ai_gateway::session::session::Session;
use crate::ai_gateway::utils::get_env_name;
use crate::ai_gateway::input::Input;



use anyhow::{anyhow, bail, Context, Result};
use is_terminal::IsTerminal;
use std::env;
use std::io::{stderr, stdin, stdout, Read};
use std::path::PathBuf;
use syntect::highlighting::ThemeSet;


/// Monokai Extended
const DARK_THEME: &[u8] = include_bytes!("./assets/monokai-extended.theme.bin");
const LIGHT_THEME: &[u8] = include_bytes!("./assets/monokai-extended-light.theme.bin");

#[derive(Debug, Clone, serde::Deserialize)]
pub struct AIGatewayConfig {
    #[serde(rename(serialize = "model", deserialize = "model"))]
    pub model_id: Option<String>,
    /// LLM temperature
    pub temperature: Option<f64>,
    pub highlight: bool,
    /// Whether to use a light theme
    pub light_theme: bool,
    /// Whether to save the session
    pub save_session: Option<bool>,
    /// Specify the text-wrapping mode (no, auto, <max-width>)
    pub wrap: Option<String>,
    /// Whether wrap code block
    pub wrap_code: bool,
    pub clients: Vec<ClientConfig>,
    #[serde(skip)]
    pub model: Model,
    #[serde(skip)]
    pub session: Option<Session>,
}

// Read config from yaml file using serde yaml and deserialize it into AI Gateway Config
impl AIGatewayConfig {
    pub fn from_yaml(yaml: &str) -> Result<Self, Box<dyn std::error::Error>> {
        let config: AIGatewayConfig = serde_yaml::from_str(yaml)?;
        Ok(config)
    }

    fn setup_model(&mut self) -> Result<()> {
        let model = match &self.model_id {
            Some(v) => v.clone(),
            None => {
                let models = list_models(self);
                if models.is_empty() {
                    bail!("No available model");
                }

                models[0].id()
            }
        };
        self.set_model(&model)?;
        Ok(())
    }

    pub fn set_model(&mut self, value: &str) -> Result<()> {
        let models = list_models(self);
        let model = Model::find(&models, value);
        match model {
            None => bail!("Invalid model '{}'", value),
            Some(model) => {
                if let Some(session) = self.session.as_mut() {
                    session.set_model(model.clone())?;
                }
                self.model = model;
                Ok(())
            }
        }
    }

    pub fn config_dir() -> Result<PathBuf> {
        let env_name = get_env_name("config_dir");
        let path = if let Some(v) = env::var_os(env_name) {
            PathBuf::from(v)
        } else {
            let mut dir = dirs::config_dir().ok_or_else(|| anyhow!("Not found config dir"))?;
            dir.push(env!("CARGO_CRATE_NAME"));
            dir
        };
        Ok(path)
    }

    pub fn local_path(name: &str) -> Result<PathBuf> {
        let mut path = Self::config_dir()?;
        path.push(name);
        Ok(path)
    }

    pub fn get_render_options(&self) -> Result<RenderOptions> {
        let theme = if self.highlight {
            let theme_mode = if self.light_theme { "light" } else { "dark" };
            let theme_filename = format!("{theme_mode}.tmTheme");
            let theme_path = Self::local_path(&theme_filename)?;
            if theme_path.exists() {
                let theme = ThemeSet::get_theme(&theme_path)
                    .with_context(|| format!("Invalid theme at {}", theme_path.display()))?;
                Some(theme)
            } else {
                let theme = if self.light_theme {
                    bincode::deserialize_from(LIGHT_THEME).expect("Invalid builtin light theme")
                } else {
                    bincode::deserialize_from(DARK_THEME).expect("Invalid builtin dark theme")
                };
                Some(theme)
            }
        } else {
            None
        };
        let wrap = if stdout().is_terminal() {
            self.wrap.clone()
        } else {
            None
        };
        let truecolor = matches!(
            env::var("COLORTERM").as_ref().map(|v| v.as_str()),
            Ok("truecolor")
        );
        Ok(RenderOptions::new(theme, wrap, self.wrap_code, truecolor))
    }

    pub fn build_messages(&self, input: &Input) -> Result<Vec<Message>> {
        let messages = if let Some(session) = input.session(&self.session) {
            session.build_emssages(input)
        } else if let Some(role) = input.role() {
            role.build_messages(input)
        } else {
            let message = Message::new(input);
            vec![message]
        };
        Ok(messages)
    }

    pub fn prepare_send_data(&self, input: &Input, stream: bool) -> Result<SendData> {
        let messages = self.build_messages(input)?;
        let temperature = if let Some(session) = input.session(&self.session) {
            session.temperature()
        } else if let Some(role) = input.role() {
            role.temperature
        } else {
            self.temperature
        };
        self.model.max_input_tokens_limit(&messages)?;
        Ok(SendData {
            messages,
            temperature,
            stream,
        })
    }
}
