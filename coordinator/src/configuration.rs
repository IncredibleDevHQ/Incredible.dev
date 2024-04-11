use crate::CONFIG;

#[allow(unused)]
#[derive(Debug, Clone)]
pub struct Configuration {
    pub environment: String,
    pub code_search_url: String,
    pub context_generator_url: String,
    pub code_understanding_url: String,
    pub code_modifier_url: String,
    pub redis_url: String,
    pub openai_url: String,
    pub openai_api_key: String,
    pub openai_model: String,
    pub ai_gateway_config: String,
}

pub fn get_redis_url() -> String {
    CONFIG.read().unwrap().redis_url.clone()
}

pub fn get_code_search_url() -> String {
    CONFIG.read().unwrap().code_search_url.clone()
}

pub fn get_context_generator_url() -> String {
    CONFIG.read().unwrap().context_generator_url.clone()
}

pub fn get_code_understanding_url() -> String {
    CONFIG.read().unwrap().code_understanding_url.clone()
}

pub fn get_code_modifier_url() -> String {
    CONFIG.read().unwrap().code_modifier_url.clone()
}

pub fn get_ai_gateway_config() -> String {
    log::debug!("Reading AI Gateway config");
    CONFIG.read().unwrap().ai_gateway_config.clone()
}

pub fn get_openai_url() -> String {
    CONFIG.read().unwrap().openai_url.clone()
}

pub fn get_openai_api_key() -> String {
    CONFIG.read().unwrap().openai_api_key.clone()
}

pub fn get_openai_model() -> String {
    CONFIG.read().unwrap().openai_model.clone()
}