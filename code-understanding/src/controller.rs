use crate::agent;
use crate::agent::agent::ANSWER_MODEL;
use crate::agent::prompts;
use crate::config::Config;
use crate::AppState;
use common::models::{CodeUnderstandRequest, GenerateQuestionRequest};
use common::{models::TaskListResponse, CodeUnderstanding};
use serde::ser::Error;
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

pub async fn generate_task_list(
    req: GenerateQuestionRequest,
    app_state: Arc<AppState>,
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

    let system_prompt: String = prompts::question_concept_generator_prompt(&issue_desc, &repo_name);
    let system_message = llm_gateway::api::Message::system(&system_prompt);
    let messages = Some(system_message).into_iter().collect::<Vec<_>>();

    let response = match llm_gateway
        .clone()
        .model(ANSWER_MODEL)
        .chat(&messages, None)
        .await
    {
        Ok(response) => Some(response),
        Err(_) => None,
    };
    let final_response = match response {
        Some(response) => response,
        None => {
            log::error!("Error: Unable to fetch response from the gateway");
            // Return error as API response
            return Ok(warp::reply::with_status(
                warp::reply::json(&format!("Error: Unable to fetch response from the gateway")),
                StatusCode::INTERNAL_SERVER_ERROR,
            ));
        }
    };

    let choices_str = final_response.choices[0]
        .message
        .content
        .clone()
        .unwrap_or_else(|| "".to_string());

    log::debug!("Choices: {}", choices_str);

    let response_task_list: Result<TaskListResponse, serde_json::Error> = serde_json::from_str(&choices_str);

    let response_task_list = match response_task_list {
        Ok(task_list) => task_list,
        Err(e) => {
            log::error!("Failed to parse choices: {}", e);
            return Ok(warp::reply::with_status(
                warp::reply::json(&"Error: Failed to parse choices".to_string()),
                StatusCode::INTERNAL_SERVER_ERROR,
            ));
        }
    };

    log::debug!("{:?}", response_task_list);

    Ok(warp::reply::with_status(
        warp::reply::json(&response_task_list),
        StatusCode::OK,
    ))
}
