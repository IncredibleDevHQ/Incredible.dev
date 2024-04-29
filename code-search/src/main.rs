use config::initialize_config;
use log::{error, info};
use std::sync::Arc;
use warp;

mod code_navigation;
mod controller;
mod db;
mod models;
mod parser;
mod routes;
mod search;
mod snippet;
mod utilities;
mod config;

extern crate reqwest;
use reqwest::Client;

#[tokio::main]
async fn main() {
    env_logger::init();
    // initialize the env configurations and database connection.
    let app_state = initialize_config().await;

    // use log library to gracefully log the error and exit the application if the app_state is not initialized.
    let app_state = match app_state {
        Ok(app_state) => Arc::new(app_state),
        Err(err) => {
            error!("Failed to initialize the app state: {}", err);
            //println!("Failed to initialize the app state: {}", err);
            std::process::exit(1);
        }
    };

    // set up the api routes
    let search_routes = routes::search_routes(app_state.clone());

    warp::serve(search_routes).run(([0, 0, 0, 0], 3003)).await;
}
