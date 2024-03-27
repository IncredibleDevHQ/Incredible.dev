#[cfg(feature = "cli")]
mod cli;

#[cfg(not(feature = "cli"))]
mod server;

#[tokio::main]
async fn main() {
    env_logger::init();
    dotenv::dotenv().ok();

    #[cfg(feature = "cli")]
    cli::execute().await;

    #[cfg(not(feature = "cli"))]
    {
        log::info!("CLI feature not enabled. Running in API mode...");

        let ingestion_routes = server::routes::ingestion();
        warp::serve(ingestion_routes)
            .run(([0, 0, 0, 0], 3001))
            .await;
        log::info!("Started web server on http://localhost:3001");
    }
}
