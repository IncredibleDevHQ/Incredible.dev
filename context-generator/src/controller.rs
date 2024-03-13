use crate::agent;
use crate::AppState;
use log::{error, info};
use std::time::Duration;

use crate::agent::agent::Action;
use crate::agent::agent::Agent;
use crate::agent::exchange::Exchange;
use crate::routes;
use agent::prompts::RetrieveCodeRequestWithUrl;
use anyhow::Result;
use std::convert::Infallible;
use std::sync::Arc;
use warp::http::StatusCode;

extern crate common;
use common::prompt_string_generator::GeneratePromptString;
use common::llm_gateway::Client;

pub async fn handle_find_context_context(
    req: routes::RetrieveCodeRequest,
    app_state: Arc<AppState>,
) -> Result<impl warp::Reply, Infallible> {
    // get search api url from app state config 
    let search_api_url = app_state.configuration.search_service_url.clone();
    
    let retrieve_code_request = RetrieveCodeRequestWithUrl{
        url: search_api_url.to_string(),
        request_data: req.clone()
    };
    // // use the questions, answer and their code spans to create header for the prompt string.
    // let prompt_string_code_context_result = retrieve_code_request.generate_prompt().await;

    // // return internal server error on error constructing prompt header
    //  if prompt_string_code_context_result.is_err() {
    //     // error warp json error with internal server error status 
    //     let error_str = format!("Unable to fetch code context: {}", prompt_string_code_context_result.err().unwrap());
    //     error!("Error constructing prompt header: {}", error_str);
    //     // error warp json error with internal server error status
    //     return Ok(warp::reply::with_status(
    //         warp::reply::json(&error_str),
    //         StatusCode::INTERNAL_SERVER_ERROR
    //     ));
    // };

    // let prompt_string_context = prompt_string_code_context_result.unwrap();

    // create a sample prompt string context for now
    let prompt_string_context = "Given the following code context, what is the purpose of the function?".to_string();
    let mut action = Action::Query(prompt_string_context.clone());
    let id = uuid::Uuid::new_v4();

    let mut exchanges = vec![Exchange::new(id, &prompt_string_context)]; 

    // get the configuration from the app state
    let configuration = &app_state.configuration;

    // intialize new llm gateway.
    let llm_gateway = Client::new(&configuration.openai_url)
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

    // send a dummy response for now
    // TODO: Fix the dummy response
    Ok(warp::reply::with_status(
        warp::reply::json(&format!("Code context fetched successfully")),
        StatusCode::OK,
    ))
}
