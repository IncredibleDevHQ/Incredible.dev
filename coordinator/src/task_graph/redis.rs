use log::{debug, info};
use crate::task_graph::graph_model::TrackProcessV1;
use anyhow::Result;
use redis::Commands;
use serde_json;

/// Serializes and stores the TaskProcessV1 instance in Redis.
pub fn save_task_process_to_redis(task_process: &TrackProcessV1) -> Result<()> {
    let mut conn = establish_redis_connection()?;

    // Use the UUID from the root node as part of the key.
    if let Some(uuid) = task_process.get_root_node_uuid() {
        let key = format!("taskprocess:{}", uuid);
        let value = serde_json::to_string(task_process)?;
        conn.set(&key, value)?;
        info!("TaskProcess saved to Redis with UUID: {}", uuid.to_string());
        Ok(())
    } else {
        // Handle the case where the UUID is not available.
        debug!("Root node UUID not found in the TaskProcess graph.");

        Err(anyhow::Error::new(std::io::Error::new(
            std::io::ErrorKind::NotFound,
            "Root node UUID not found in the TaskProcess graph.",
        )))
    }
}

/// Reads and deserializes a TaskProcessV1 instance from Redis by UUID.
pub fn load_task_process_from_redis(uuid: &str) -> Result<TrackProcessV1> {
    let key = format!("taskprocess:{}", uuid);
    let mut conn = establish_redis_connection()?;
    let value: String = conn.get(&key)?;
    let task_process: TrackProcessV1 = serde_json::from_str(&value)?;
    Ok(task_process)
}

fn establish_redis_connection() -> redis::RedisResult<redis::Connection> {
    // Specify the Redis URL
    let redis_url = "redis://127.0.0.1:6379/";

    // Attempt to establish a connection
    let client = redis::Client::open(redis_url)?;
    let mut conn = client.get_connection()?;

    // Test the connection
    let _: () = conn.set("test_key", "test_value")?;
    let test_value: String = conn.get("test_key")?;
    assert_eq!(test_value, "test_value");

    println!("Connected to Redis successfully!");

    Ok(conn)
}
