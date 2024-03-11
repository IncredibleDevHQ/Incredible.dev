use crate::agent;
use crate::AppState;
use agent::llm_gateway;
use common::prompt_string_generator;
use futures::StreamExt;
use log::{error, info};
use std::time::Duration;

use crate::agent::agent::Action;
use crate::agent::agent::Agent;
use crate::agent::exchange::Exchange;
use crate::routes;
use agent::prompts::RetrieveCodeRequestWithUrl;
use anyhow::{Result, format_err};
use std::convert::Infallible;
use std::sync::Arc;
use warp::http::StatusCode;

extern crate common;
use common::prompt_string_generator::GeneratePromptString;

pub async fn handle_find_context_context(
    req: routes::RetrieveCodeRequest,
    app_state: Arc<AppState>,
) -> Result<impl warp::Reply, Infallible> {
    // create an instance of retreive code request with url using req and url 
    // use localhost:8080/span as the url
    // TODO: Remove the hardcoded URL
    let retrieve_code_request = RetrieveCodeRequestWithUrl{
        url: "http://localhost:8080/span".to_string(),
        request_data: req.clone()
    };
    // use the questions, answer and their code spans to create header for the prompt string.
    let prompt_string_code_context_result = retrieve_code_request.generate_prompt().await;

    // return internal server error on error constructing prompt header
     if prompt_string_code_context_result.is_err() {
        // error warp json error with internal server error status 
        let error_str = format!("Unable to fetch code context: {}", prompt_string_code_context_result.err().unwrap());
        error!("Error constructing prompt header: {}", error_str);
        // error warp json error with internal server error status
        return Ok(warp::reply::with_status(
            warp::reply::json(&error_str),
            StatusCode::INTERNAL_SERVER_ERROR
        ));

    };

    let prompt_string_context = prompt_string_code_context_result.unwrap();

    let mut action = Action::Query(prompt_string_context);
    let id = uuid::Uuid::new_v4();

    let mut exchanges = vec![Exchange::new(id, &prompt_string_context)]; 

    // get the configuration from the app state
    let configuration = &app_state.configuration;

    // intialize new llm gateway.
    let llm_gateway = llm_gateway::Client::new(&configuration.openai_url)
        .temperature(0.0)
        .bearer(configuration.openai_key.clone())
        .model(&configuration.openai_model.clone());

    // get db client from app state

    let mut agent: Agent = Agent {
        app_state: app_state,
        exchanges,
        llm_gateway,
        query_id: id,
        complete: false,
    };

    // first action
    info!("first action {:?}\n", action);

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

    Ok(warp::reply::with_status(
        warp::reply::json(&response),
        StatusCode::OK,
    ))
}
