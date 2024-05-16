use config::initialize_config;
use log::error;
use std::{env, sync::Arc};
use warp;

mod code_navigation;
mod config;
mod controller;
mod db;
mod models;
mod parser;
mod routes;
mod search;
mod snippet;
mod utilities;

extern crate reqwest;

#[tokio::main]
async fn main() {
    env_logger::init();
    // Parse command line arguments
    let args: Vec<String> = env::args().collect();
    let mut env_file: Option<String> = None;

    if args.len() > 1 {
        for i in 1..args.len() {
            if args[i] == "--env-file" {
                if i + 1 < args.len() {
                    env_file = Some(args[i + 1].clone());
                } else {
                    log::error!("--env-file requires a value");
                    std::process::exit(1);
                }
            }
        }
    }

    // Initialize the env configurations and database connection
    let app_state = initialize_config(env_file).await;

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
