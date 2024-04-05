use crate::ai_gateway::client::{ClientConfig, list_models, Model};
use anyhow::bail;

#[derive(Debug, Clone, serde::Deserialize)]
pub struct AIGatewayConfig {
    #[serde(rename(serialize = "model", deserialize = "model"))]
    pub model_id: Option<String>,
    pub client_config: Vec<ClientConfig>,
    #[serde(skip)]
    pub model: Model,

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
}