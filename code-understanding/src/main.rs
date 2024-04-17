use anyhow::Result;
use redis;
use common::task_graph::{redis::establish_redis_connection, redis_config::get_redis_url};
use once_cell::sync::Lazy;
use std::sync::{Once, RwLock};
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
struct AppState {
    db_connection: db_client::DbConnect, // Assuming DbConnection is your database connection type
    redis_conn: redis::Connection,
}

// initialize the app state with the configuration and database connection.
async fn init_state() -> Result<AppState, anyhow::Error> {
    // call the search url home route and see if the server is running. If not return a message to the user to first start the server.
    let search_url = format!("{}/", get_search_server_url());
    let response = reqwest::get(&search_url).await;
    match response {
        Ok(_) => {
            log::info!("Search server is running at {}", search_url);
        }
        Err(_) => {
            log::error!("Search server is not running. Please start the search server first.");
            return Err(anyhow::anyhow!("Search server is not running. Please start the search server first."));
        }
    }

    let redis_client = establish_redis_connection(&get_redis_url())?;

    // create new db client.
    let db_client = match db_client::DbConnect::new().await {
        Ok(client) => client,
        Err(_) => {
            log::error!("Initializing database failed.");
            return Err(anyhow::anyhow!("Initializing database failed."));
        }
    };

    Ok(AppState {
        redis_conn: redis_client,
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
