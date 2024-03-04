use crate::agent;
use crate::AppState;
use agent::llm_gateway;
use futures::StreamExt;
use log::{error, info};
use std::time::Duration;

use crate::agent::agent::Action;
use crate::agent::agent::Agent;
use crate::agent::exchange::Exchange;
use crate::parser::parser::{parse_query_target, parse_query};
use crate::routes;
use anyhow::Result;
use std::convert::Infallible;
use std::sync::Arc;
use warp::http::StatusCode;

pub async fn handle_retrieve_code(
    req: routes::RetrieveCodeRequest,
    app_state: Arc<AppState>,
) -> Result<impl warp::Reply, Infallible> {
    info!("Query: {}, Repo: {}", req.query, req.repo);

    // Combine query and repo_name in the response
    let response = format!("Query: '{}', Repo: '{}'", req.query, req.repo);

    // if query or repo is empty, return bad request.
    if req.query.is_empty() || req.repo.is_empty() {
        error!("Query or Repo from the user request is empty");
        return Ok(warp::reply::with_status(
            warp::reply::json(&format!("Error: Query or Repo is empty")),
            StatusCode::BAD_REQUEST,
        ));
    }

    // parse the query
    let query_clone = req.query.clone();
    let parsed_query = parse_query(req.query.clone());
    // if the query is not parsed, return internal server error.
    if parsed_query.is_err() {
        error!("Error parsing the query");
        return Ok(warp::reply::with_status(
            warp::reply::json(&format!("Error: {}", parsed_query.err().unwrap())),
            StatusCode::INTERNAL_SERVER_ERROR,
        ));
    }

    let parsed_query = parsed_query.unwrap();   
    let query_target = parse_query_target(&parsed_query);
    // if the query target is not parsed, return internal server error.
    if query_target.is_err() {
        error!("Error parsing the query target");
        return Ok(warp::reply::with_status(
            warp::reply::json(&format!("Error: {}", query_target.err().unwrap())),
            StatusCode::INTERNAL_SERVER_ERROR,
        ));
    }

    let query_target = query_target.unwrap();
    info!("Query target{:?}", query_target);

    let mut action = Action::Query(query_target);
    let id = uuid::Uuid::new_v4();

    let mut exchanges = vec![agent::exchange::Exchange::new(id, parsed_query.clone())];
    exchanges.push(Exchange::new(id, parsed_query));

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
