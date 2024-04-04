use once_cell::sync::Lazy;
use std::sync::Mutex;

struct Config {
    redis_url: String,
}

static CONFIG: Lazy<Mutex<Config>> = Lazy::new(|| {
    Mutex::new(Config {
        redis_url: String::new(),
    })
});

pub fn set_redis_url(redis_url: &str) {
    let mut config = CONFIG.lock().unwrap();
    config.redis_url = redis_url.to_string();
}

pub fn get_redis_url() -> String {
    let config = CONFIG.lock().unwrap();
    config.redis_url.clone()
}
