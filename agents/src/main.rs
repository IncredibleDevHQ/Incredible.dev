use anyhow::Result;

mod agent;
mod config;
mod db_client;
mod helpers;
mod parser;
mod question_generator;
mod routes;
mod search;
mod utils;

use core::result::Result::Ok;

#[tokio::main]
async fn main() -> Result<()> {
    env_logger::init();
    let code_retrieve_routes = routes::code_retrieve();

    warp::serve(code_retrieve_routes)
        .run(([0, 0, 0, 0], 3001))
        .await;

    Ok(())
}
