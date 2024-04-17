use crate::task_graph::graph_model::TrackProcessV1;
use anyhow::Result;
use log::{debug, info};
use redis::Commands;
use serde_json;

impl TrackProcessV1 {
    /// Serializes and stores the TaskProcessV1 instance in Redis.
    pub fn save_task_process_to_redis(&self, redis_url: &str)  -> Result<()> {
        let mut conn = establish_redis_connection(redis_url)?;

        // Use the UUID from the root node as part of the key.
        if let Some(uuid) = self.get_root_node_uuid() {
            let key = format!("taskprocess:{}", uuid);
            let value = serde_json::to_string(self)?;
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
}
 /// Reads and deserializes a TaskProcessV1 instance from Redis by UUID.
 pub fn load_task_process_from_redis(url: &str, uuid: &str) -> Result<TrackProcessV1> {
    let key = format!("taskprocess:{}", uuid);
    let mut conn = establish_redis_connection(url)?;
    let value: String = conn.get(&key)?;
    let task_process: TrackProcessV1 = serde_json::from_str(&value)?;
    Ok(task_process)
}

pub fn establish_redis_connection(url: &str) -> redis::RedisResult<redis::Connection> {
    // Attempt to establish a connection
    let client = redis::Client::open(url)?;
    let mut conn: redis::Connection = client.get_connection()?;

    // Test the connection
    let _: () = conn.set("test_key", "test_value")?;
    let test_value: String = conn.get("test_key")?;
    assert_eq!(test_value, "test_value");

    info!("Connected to Redis successfully!");

    Ok(conn)
}