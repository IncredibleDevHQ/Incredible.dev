use once_cell::sync::Lazy;
use std::sync::RwLock;

static REDIS_URL: Lazy<RwLock<String>> = Lazy::new(|| {
    RwLock::new(String::from("default_redis_url")) // Default URL or leave it empty.
});

pub fn set_redis_url(redis_url: &str) {
    let mut url = REDIS_URL.write().unwrap(); // Acquire a write lock
    *url = redis_url.to_string();
}

pub fn get_redis_url() -> String {
    let url = REDIS_URL.read().unwrap(); // Acquire a read lock
    url.clone()
}
