use anyhow::Result;
use log::{error, info};

mod agent;
mod config;
mod db_client;
mod helpers;
mod parser;
mod routes;
mod search;
mod utils;

use core::result::Result::Ok;
struct AppState {
    configuration: config::Config,
    db_connection: db_client::DbConnect,  // Assuming DbConnection is your database connection type
}

// initialize the app state with the configuration and database connection.
async fn init_state() -> Result<AppState, anyhow::Error> {
    let configuration = config::Config::new().await?;

    let db_connection = db_client::init_db(configuration.clone()).await?;

    Ok(AppState {
        configuration,
        db_connection,
    })
}

#[tokio::main]
async fn main() -> Result<()> {
    env_logger::init();
    
    // initialize the env configurations and database connection.
    let app_state = init_state().await;

    // Exit the process with a non-zero code if the app state is not initialized.
    let app_state = match app_state {
        Ok(app_state) => app_state,
        Err(err) => {
            error!("Failed to initialize app state: {}", err);
            std::process::exit(1);
        }
    };

    let code_retrieve_routes = routes::code_retrieve();

    warp::serve(code_retrieve_routes)
        .run(([0, 0, 0, 0], 3001))
        .await;

    Ok(())
}
