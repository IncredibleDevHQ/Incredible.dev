pub mod cli;

#[tokio::main]
async fn main() {
    env_logger::init();
    cli::execute().await;
}
