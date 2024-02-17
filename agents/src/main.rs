use anyhow::{Context, Error, Result};
use futures::{future::Either, stream, StreamExt};
use std::time::Duration;
use tokio_stream::Stream;

mod agent;
mod db_client;
mod helpers;
mod parser;
mod search;

use crate::agent::agent::Action;
use crate::agent::agent::Agent;
use crate::agent::agent::AgentError;
use crate::agent::exchange::Exchange;

use agent::llm_gateway;
use async_stream::__private::AsyncStream;
use core::result::Result::Ok;
use std::io::Write;

// derive debug and clone for configuration.
#[derive(Debug, Clone)]
pub struct Configuration {
    semantic_collection_name: String,
    repo_name: String,
    semantic_url: String,
    tokenizer_path: String,
    model_path: String,
    openai_key: String,
    openai_url: String,
    openai_model: String,
}

const TIMEOUT_SECS: u64 = 60;

#[tokio::main]
async fn main() -> Result<()> {
    println!("Hello, world!=========================================================================");

    let q = "How are github app private keys handled?";

    let query = parser::parser::parse_nl(q)
        .context("parse error")?
        .into_semantic()
        .context("got a 'Grep' query")?
        .into_owned();
    println!("{:?}", query);
    let query_target = query
        .target
        .as_ref()
        .context("query was empty")?
        .as_plain()
        .context("user query was not plain text")?
        .clone()
        .into_owned();
    println!("{:?}", query_target);

    let mut action = Action::Query(query_target);


    let id = uuid::Uuid::new_v4();
    // create array of  exchanges.
    let mut exchanges = vec![agent::exchange::Exchange::new(id, query.clone())];
    exchanges.push(Exchange::new(id, query));

    // create new configuration.
    let configuration = Configuration {
        repo_name: "bloop-ai".to_string(),
        semantic_collection_name: "documents".to_string(),
        semantic_url: "http://localhost:6334".to_string(),
        tokenizer_path:
            "./model/tokenizer.json"
                .to_string(),
        model_path: "./model/model.onnx"
            .to_string(),
        openai_key: "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".to_string(),
        openai_url: "https://api.openai.com".to_string(),
        openai_model: "gpt-4".to_string(),
    };

    // intialize new llm gateway.
    let llm_gateway = llm_gateway::Client::new(&configuration.openai_url)
        .temperature(0.0)
        .bearer(configuration.openai_key.clone())
        .model(&configuration.openai_model.clone());

    // create new db client.
    let db_client = db_client::DbConnect::new(configuration)
        .await
        .context("Initiazing database failed.")?;

    // create agent.

    let (exchange_tx, exchange_rx) = tokio::sync::mpsc::channel(10);

    let mut agent: Agent = Agent {
        db: db_client,
        exchange_tx: exchange_tx,
        exchanges: exchanges,
        llm_gateway: llm_gateway,
        query_id: id,
        complete: false,
    };
    // ... [ rest of the setup code ]

    let mut exchange_stream = tokio_stream::wrappers::ReceiverStream::new(exchange_rx);

    let exchange_handler = tokio::spawn(async move {
        while let exchange = exchange_stream.next().await {
            match exchange {
                Some(e) => {
                    //println!("{:?}", e.compressed());
                }
                None => {
                    eprintln!("No more messages or exchange channel was closed.");
                    break;
                }
            }
        }
    });

    // first action
    println!("first action {:?}\n", action);

    let mut i = 1;
    'outer: loop {
        // Now only focus on the step function inside this loop.
        match agent.step(action).await {
            Ok(next_action) => {
                match next_action {
                    Some(act) => { 
                        action = act;
                    }
                    None => { break }
                }
             
                // print the action
                i = i + 1;

                println!("Action number: {}, Action: {:?}",i,  action);
            }
            Err(e) => {
                eprintln!("Error during processing: {}", e);
                break 'outer;
            }
        }

        // Optionally, you can add a small delay here to prevent the loop from being too tight.
        tokio::time::sleep(Duration::from_millis(500)).await;
    }

    agent.complete();

    // Await the spawned task to ensure it has completed.
    // Though it's not strictly necessary in this context since the task will end on its own when the stream ends.
    let _ = exchange_handler.await;

    // ... [ rest of your code ]

    Ok(())
}
