use crate::agent;
use crate::agent::agent::ANSWER_MODEL;
use crate::agent::prompts;
use crate::config::Config;
use crate::AppState;
use agent::llm_gateway;
use common::CodeUnderstanding;
use std::time::Duration;

use crate::agent::agent::Action;
use crate::agent::agent::Agent;
use crate::agent::exchange::Exchange;
use crate::parser::parser::{parse_query, parse_query_target};
use crate::routes;
use anyhow::Result;
use serde::Deserialize;
use std::convert::Infallible;
use std::sync::Arc;
use warp::http::StatusCode;

pub async fn handle_retrieve_code(
    req: routes::RetrieveCodeRequest,
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

    let parsed_query = parse_query(req.query.clone());
    // if the query is not parsed, return internal server error.
    if parsed_query.is_err() {
        log::error!("Error parsing the query");
        return Ok(warp::reply::with_status(
            warp::reply::json(&format!("Error: {}", parsed_query.err().unwrap())),
            StatusCode::INTERNAL_SERVER_ERROR,
        ));
    }

    let parsed_query = parsed_query.unwrap();
    let query_target = parse_query_target(&parsed_query);
    // if the query target is not parsed, return internal server error.
    if query_target.is_err() {
        log::error!("Error parsing the query target");
        return Ok(warp::reply::with_status(
            warp::reply::json(&format!("Error: {}", query_target.err().unwrap())),
            StatusCode::INTERNAL_SERVER_ERROR,
        ));
    }

    let query_target = query_target.unwrap();
    log::info!("Query target{:?}", query_target);

    let mut action = Action::Query(query_target);
    let id = uuid::Uuid::new_v4();

    let mut exchanges = vec![];
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
        repo_name: req.repo.clone(),
    };

    // first action
    log::info!("first action {:?}\n", action);

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

                log::info!("Action number: {}, Action: {:?}", i, action);
            }
            Err(e) => {
                log::error!("Error during processing: {}", e);
                break 'outer;
            }
        }

        // Optionally, you can add a small delay here to prevent the loop from being too tight.
        tokio::time::sleep(Duration::from_millis(500)).await;
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

#[derive(Debug, Deserialize)]

pub struct GenerateQuestionRequest {
    pub issue_desc: String,
    pub repo_name: String,
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

    let response_questions: Vec<String> = match serde_json::from_str(&choices_str) {
        Ok(c) => c,
        Err(_) => {
            return Ok(warp::reply::with_status(
                warp::reply::json(&format!("Error: Failed to parse choices")),
                StatusCode::INTERNAL_SERVER_ERROR,
            ));
        }
    };

    println!("Response: {}", choices_str);

    Ok(warp::reply::with_status(
        warp::reply::json(&response_questions),
        StatusCode::OK,
    ))
}

pub async fn generate_question_array_v2(
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
    let response_questions: Vec<String> = match serde_json::from_str(&choices_str) {
        Ok(c) => c,
        Err(_) => {
            return Ok(warp::reply::with_status(
                warp::reply::json(&format!("Error: Failed to parse choices")),
                StatusCode::INTERNAL_SERVER_ERROR,
            ));
        }
    };

    println!("Response: {}", choices_str);

    Ok(warp::reply::with_status(
        warp::reply::json(&response_questions),
        StatusCode::OK,
    ))
}