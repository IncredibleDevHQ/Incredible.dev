use anyhow::Result;
use futures::future::join_all;
use std::{collections::HashMap, convert::Infallible};

use common::{
    models::{CodeContextRequest, CodeUnderstandRequest, GenerateQuestionRequest},
    service_interaction::service_caller,
    CodeUnderstanding, CodeUnderstandings,
};
use reqwest::{Method, StatusCode};

use crate::{models::SuggestRequest, CONFIG};

pub async fn handle_suggest_wrapper(
    request: SuggestRequest,
) -> Result<impl warp::Reply, Infallible> {
    match handle_suggest_core(request).await {
        Ok(response) => Ok(warp::reply::with_status(
            warp::reply::json(&response),
            StatusCode::OK,
        )),
        Err(e) => {
            log::error!("Error processing modify code request: {}", e);
            // TODO: Convert the error message into a structured error response
            let error_message = format!("Error processing request: {}", e);
            Ok(warp::reply::with_status(
                warp::reply::json(&error_message),
                StatusCode::INTERNAL_SERVER_ERROR,
            ))
        }
    }
}

async fn handle_suggest_core(request: SuggestRequest) -> Result<CodeUnderstandings, anyhow::Error> {
    let generated_questions = match get_generated_questions(
        request.user_query.clone(),
        request.repo_name.clone(),
    )
    .await
    {
        Ok(questions) => questions,
        Err(e) => {
            log::error!("Failed to generate questions: {}", e);
            return Err(e);
        }
    };

    let answers_to_questions =
        match get_code_understandings(request.repo_name.clone(), generated_questions).await {
            Ok(answers) => answers,
            Err(e) => {
                log::error!("Failed to get answers to questions: {}", e);
                return Err(e);
            }
        };

    let code_context_request = CodeUnderstandings {
        repo: request.repo_name.clone(),
        issue_description: request.user_query.clone(),
        qna: answers_to_questions.clone(),
    };
    // TODO: Uncomment this once the context generator is implemented
    // let code_contexts = match get_code_context(code_context_request).await {
    //     Ok(contexts) => contexts,
    //     Err(e) => {
    //         log::error!("Failed to get code contexts: {}", e);
    //         return Err(e);
    //     }
    // };

    Ok(code_context_request)
}

async fn get_generated_questions(
    user_query: String,
    repo_name: String,
) -> Result<Vec<String>, anyhow::Error> {
    let generate_questions_url = format!("{}/question-list", CONFIG.code_understanding_url);
    let generated_questions = service_caller::<GenerateQuestionRequest, Vec<String>>(
        generate_questions_url,
        Method::POST,
        Some(GenerateQuestionRequest {
            issue_desc: user_query,
            repo_name: repo_name,
        }),
        None,
    )
    .await?;

    Ok(generated_questions)
}

async fn get_code_understandings(
    repo_name: String,
    generated_questions: Vec<String>,
) -> Result<Vec<CodeUnderstanding>, anyhow::Error> {
    let code_understanding_url = format!("{}/retrieve-code", CONFIG.code_understanding_url);
    let futures_answers_for_questions: Vec<_> = generated_questions
        .iter()
        .map(|question| {
            let url = code_understanding_url.clone();
            let mut query_params = HashMap::new();
            query_params.insert("query".to_string(), question.clone());
            query_params.insert("repo".to_string(), repo_name.clone());
            async move {
                service_caller::<CodeUnderstandRequest, CodeUnderstanding>(
                    url,
                    Method::GET,
                    None,
                    Some(query_params),
                )
                .await
            }
        })
        .collect();

    let answers_for_questions = join_all(futures_answers_for_questions).await;

    let successful_responses = answers_for_questions
        .into_iter()
        .filter_map(|result| match result {
            Ok(understandings) => Some(understandings),
            Err(e) => {
                log::error!("Failed to process question: {}", e);
                None
            }
        })
        .collect();

    Ok(successful_responses)
}

// TODO: Remove unused warning suppressor once the context generator is implemented
#[allow(unused)]
async fn get_code_context(code_understanding: CodeUnderstandings) -> Result<String, anyhow::Error> {
    let code_context_url = format!("{}/find-code-context", CONFIG.context_generator_url);
    let code_context = service_caller::<CodeContextRequest, String>(
        code_context_url,
        Method::POST,
        Some(CodeContextRequest {
            qna_context: code_understanding.clone(),
        }),
        None,
    )
    .await?;

    Ok(code_context)
}
