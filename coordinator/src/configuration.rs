use crate::CONFIG;

#[allow(unused)]
#[derive(Debug, Clone)]
pub struct Configuration {
    pub code_search_url: String,
    pub code_understanding_url: String,
    pub redis_url: String,
    pub ai_gateway_config: String,
}

pub fn get_redis_url() -> String {
    CONFIG.read().unwrap().redis_url.clone()
}

pub fn get_code_search_url() -> String {
    CONFIG.read().unwrap().code_search_url.clone()
}

pub fn get_code_understanding_url() -> String {
    CONFIG.read().unwrap().code_understanding_url.clone()
}

pub fn get_ai_gateway_config() -> String {
    log::debug!("Reading AI Gateway config");
    CONFIG.read().unwrap().ai_gateway_config.clone()
}