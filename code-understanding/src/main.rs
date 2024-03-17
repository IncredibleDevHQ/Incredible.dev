use anyhow::Result;
use lazy_static::lazy_static;
use std::sync::Once;
use config::Config;

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
    configuration: &'static config::Config,
    db_connection: db_client::DbConnect, // Assuming DbConnection is your database connection type
}

// initialize the app state with the configuration and database connection.
async fn init_state() -> Result<AppState, anyhow::Error> {
    let configuration = get_config(); 
    // call the search url home route and see if the server is running. If not return a message to the user to first start the server.
    let search_url = format!("{}/", configuration.search_server_url);
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

    // create new db client.
    let db_client = match db_client::DbConnect::new(&configuration).await {
        Ok(client) => client,
        Err(_) => {
            log::error!("Initializing database failed.");
            return Err(anyhow::anyhow!("Initializing database failed."));
        }
    };

    Ok(AppState {
        configuration,
        db_connection: db_client,
    })
}


// Global variable to hold the configuration
lazy_static! {
    static ref CONFIG: Config = {
        Config::new().expect("Failed to load configuration")
    };
}

// Initialize once to ensure that the global variable is only initialized once
static INIT: Once = Once::new();

// Function to access the global CONFIG variable
pub fn get_config() -> &'static Config {
    // Ensure that the global variable is initialized only once
    INIT.call_once(|| {});
    &CONFIG
}

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
