use crate::agent;
use crate::agent::agent::ANSWER_MODEL;
use crate::agent::prompts;
use crate::db_client;
use agent::llm_gateway;
use futures::StreamExt;
use log::{error, info};
use std::time::Duration;

use crate::agent::agent::Action;
use crate::agent::agent::Agent;
use crate::agent::exchange::Exchange;
use crate::config::Config;
use crate::parser;
use crate::routes;
use anyhow::Result;
use core::panic;
use std::convert::Infallible;
use warp::http::StatusCode;

pub struct GenerateQuestionRequest {
    pub issue_desc: String,
    pub repo_name: String,
}

pub async fn handle_retrieve_code(
    req: routes::RetrieveCodeRequest,
) -> Result<impl warp::Reply, Infallible> {
    info!("Query: {}, Repo: {}", req.query, req.repo);
    // Combine query and repo_name in the response
    let response = format!("Query: '{}', Repo: '{}'", req.query, req.repo);

    let query = req.query;

    let query_clone = query.clone();

    let parse_query = match parser::parser::parse_nl(&query_clone) {
        Ok(parsed) => {
            // Adjust handling for `Option` type returned by `into_semantic`
            match parsed.into_semantic() {
                Some(semantic) => semantic.into_owned(),
                None => {
                    // Handle the case where `into_semantic` returns `None`
                    eprintln!("Error: got a 'Grep' query");
                    // Use panic or consider a more graceful way to handle this scenario
                    panic!("Error: got a 'Grep' query");
                }
            }
        }
        Err(_) => {
            // Handle parse error, e.g., log it
            eprintln!("Error: parse error");
            // Since we can't return errors, consider logging or a default action
            panic!("Error parsing query");
        }
    };

    let query_target = match parse_query.target.as_ref() {
        Some(target) => match target.as_plain() {
            Some(plain) => plain.clone().into_owned(),
            None => {
                eprintln!("Error: user query was not plain text");
                panic!("Error: user query was not plain text");
            }
        },
        None => {
            eprintln!("Error: query was empty");
            panic!("Error: query was empty");
        }
    };

    println!("{:?}", query_target);

    let mut action = Action::Query(query_target);
    let id = uuid::Uuid::new_v4();

    let mut exchanges = vec![agent::exchange::Exchange::new(id, parse_query.clone())];
    exchanges.push(Exchange::new(id, parse_query));

    let configuration = Config::new().unwrap();

    // intialize new llm gateway.
    let llm_gateway = llm_gateway::Client::new(&configuration.openai_url)
        .temperature(0.0)
        .bearer(configuration.openai_key.clone())
        .model(&configuration.openai_model.clone());

    // create new db client.
    let db_client = match db_client::DbConnect::new().await {
        Ok(client) => client,
        Err(_) => {
            eprintln!("Initializing database failed.");
            // Since the function's return type is Infallible, you cannot return an error.
            // Depending on your application's needs, you might decide to panic, or if there's
            // a logical non-failing action to take, do that instead.
            panic!("Critical error: Initializing database failed.");
        }
    };

    let (exchange_tx, exchange_rx) = tokio::sync::mpsc::channel(10);

    let mut agent: Agent = Agent {
        db: db_client,
        exchange_tx,
        exchanges,
        llm_gateway,
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
                    None => break,
                }

                // print the action
                i = i + 1;

                println!("Action number: {}, Action: {:?}", i, action);
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
    let final_answer = agent.get_final_anwer().answer.unwrap();

    Ok(warp::reply::with_status(
        warp::reply::json(&final_answer),
        StatusCode::OK,
    ))
    // Err(e) => Ok(warp::reply::with_status(
    //     warp::reply::json(&format!("Error: {}", e)),
    //     StatusCode::INTERNAL_SERVER_ERROR,
    // )),
}

pub async fn generate_question_array(
    req: GenerateQuestionRequest,
) -> Result<impl warp::Reply, Infallible> {
    // info!("Query: {}, Repo: {}", req.issue_desc, req.repo);

    let configuration = Config::new().unwrap();

    let issue_desc = req.issue_desc;
    let repo_name = req.repo_name;
    // intialize new llm gateway.
    let llm_gateway = llm_gateway::Client::new(&configuration.openai_url)
        .temperature(0.0)
        .bearer(configuration.openai_key.clone())
        .model(&configuration.openai_model.clone());

    let system_prompt: String = prompts::question_generator_prompt(&issue_desc, &repo_name);
    let system_message = llm_gateway::api::Message::system(&system_prompt);
    let messages = Some(system_message).into_iter().collect::<Vec<_>>();
    let mut response = llm_gateway
        .clone()
        .model(ANSWER_MODEL)
        .chat(&messages, None)
        .await?;

    let mut question_array = vec![];

    question_array
}
