use anyhow::Result;
use once_cell::sync::Lazy;
use std::{sync::RwLock, thread::sleep, time::Duration};
use config::{get_search_server_url, load_from_env, Config};

mod agent;
mod config;
mod controller;
mod db_client;
mod helpers;
mod parser;
mod routes;
mod search;
use std::sync::Arc;

use core::result::Result::Ok;
use redis;
struct AppState {
    db_connection: db_client::DbConnect, // Assuming DbConnection is your database connection type
}

// initialize the app state with the configuration and database connection.
async fn init_state() -> Result<AppState, anyhow::Error> {
    let search_url = format!("{}/", get_search_server_url());

    // Attempt to connect to the search server with retry logic
    let mut attempts = 0;
    let max_attempts = 2; // Try once initially and retry once
    while attempts < max_attempts {
        let response = reqwest::get(&search_url).await;

        match response {
            Ok(_) => {
                log::info!("Search server is running at {}", search_url);
                break; // Exit the loop on success
            }
            Err(e) if attempts < max_attempts - 1 => {
                log::debug!("Search server not available, waiting 5 seconds before retrying...");
                sleep(Duration::from_secs(5)); // Wait for 5 seconds
                attempts += 1; // Increment the retry counter
            }
            Err(_) => {
                log::error!("Search server is not running after retries. Please start the search server first.");
                return Err(anyhow::anyhow!("Search server is not running. Please start the search server first."));
            }
        }
    }


    // create new db client.
    let db_client = match db_client::DbConnect::new().await {
        Ok(client) => client,
        Err(_) => {
            log::error!("Initializing database failed.");
            return Err(anyhow::anyhow!("Initializing database failed."));
        }
    };

    Ok(AppState {
        db_connection: db_client,
    })
}

// global configuration while RwLock is used to ensure thread safety
// Rwlock makes reads cheap, which is important because we will be reading the configuration a lot, and never mutate it after it is set.
static CONFIG: Lazy<RwLock<Config>> = Lazy::new(|| {
    // Directly load the configuration when initializing CONFIG.
    RwLock::new(load_from_env())
});

#[tokio::main]
async fn main() -> Result<()> {
    env_logger::init();
    // initialize the env configurations and database connection.
    let app_state = init_state().await;

    // Exit the process with a non-zero code if the app state is not initialized.
    let app_state = match app_state {
        Ok(app_state) => Arc::new(app_state),
        Err(err) => {
            log::error!("Failed to initialize app state: {}", err);
            std::process::exit(1);
        }
    };

    let code_retrieve_routes = routes::code_retrieve(app_state);

    warp::serve(code_retrieve_routes)
        .run(([0, 0, 0, 0], 3002))
        .await;

    Ok(())
}
