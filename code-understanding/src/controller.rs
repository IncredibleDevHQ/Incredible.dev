use crate::config::get_openai_url;
use crate::AppState;
use common::models::CodeUnderstandRequest;
use common::CodeUnderstanding;
use std::time::Duration;

use crate::agent::agent::Action;
use crate::agent::agent::Agent;
use crate::agent::exchange::Exchange;
use anyhow::Result;
use std::convert::Infallible;
use std::sync::Arc;
use warp::http::StatusCode;

use log::error;
extern crate common;
use common::llm_gateway;

pub async fn handle_retrieve_code(
    req: CodeUnderstandRequest,
    app_state: Arc<AppState>,
) -> Result<impl warp::Reply, Infallible> {
    log::info!("Query: {}, Repo: {}", req.query, req.repo);

    // if query or repo is empty, return bad request.
    if req.query.is_empty() || req.repo.is_empty() {
        log::error!("Query or Repo from the user request is empty");
        return Ok(warp::reply::with_status(
            warp::reply::json(&format!("Error: Query or Repo is empty")),
            StatusCode::BAD_REQUEST,
        ));
    }

    let mut action = Action::Query(req.query.clone());
    let id = uuid::Uuid::new_v4();

    let mut exchanges = vec![];
    exchanges.push(Exchange::new(id, req.query.clone()));

    // get the configuration from the global config
    let configuration = get_openai_url();

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
        repo_name: req.repo.clone(),
    };

    // first action
    log::info!("first action {:?}\n", action);

    let mut i = 1;
    // return error from the loop if there is an error in the action.
    let action_result: Result<(), anyhow::Error> = loop {
        // Now only focus on the step function inside this loop.
        match agent.step(action).await {
            Ok(next_action) => {
                match next_action {
                    Some(act) => {
                        action = act;
                    }
                    None => break Ok(()),
                }

                i += 1;

                log::info!("Action number: {}, Action: {:?}", i, action);
            }
            Err(e) => {
                log::error!("Error during step function: {}", e);
                break Err(e.into()); // Convert the error into a Box<dyn std::error::Error>
            }
        }

        // Optionally, you can add a small delay here to prevent the loop from being too tight.
        tokio::time::sleep(Duration::from_millis(500)).await;
    };

    // if there is an error in the action, return the error.
    if action_result.is_err() {
        let err_msg = action_result.err().unwrap().to_string();
        // log the error
        error!("Error in the step function: {}", err_msg);
        return Ok(warp::reply::with_status(
            warp::reply::json(&format!("Error: {}", err_msg)),
            StatusCode::INTERNAL_SERVER_ERROR,
        ));
    }

    // These need to be put beind a try catch sort of setup
    let final_answer = match agent.get_final_anwer().answer.clone() {
        Some(ans) => ans,
        None => {
            log::error!("Error getting final answer");
            return Ok(warp::reply::with_status(
                warp::reply::json(&format!("Error: {}", "Error getting final answer")),
                StatusCode::INTERNAL_SERVER_ERROR,
            ));
        }
    };
    let final_context = agent.get_final_anwer().final_context.clone();
    agent.complete();

    Ok(warp::reply::with_status(
        warp::reply::json(&CodeUnderstanding {
            question: req.query.clone(),
            answer: final_answer.clone(),
            context: final_context.clone(),
        }),
        StatusCode::OK,
    ))
}
