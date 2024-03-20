use anyhow::Result;
use futures::future::join_all;
use std::{collections::HashMap, convert::Infallible};
use crate::task_graph::graph_model::{TrackProcess, ChildTaskStatus};

use common::{
    models::{CodeContextRequest, CodeUnderstandRequest, GenerateQuestionRequest, TaskList},
    service_interaction::service_caller,
    CodeUnderstanding, CodeUnderstandings,
};
use reqwest::{Method, StatusCode};

use crate::{models::SuggestRequest, CONFIG};
use log::debug;

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

async fn handle_suggest_core(request: SuggestRequest) -> Result<TaskList, anyhow::Error> {
    // initialize the new tracker with task graph
    let mut tracker = TrackProcess::new(&request.repo_name, &request.user_query);

    // update root status to in progress
    // the status is used to track of the processing of its child nodes 
    // in this the child elelments are tasks, subtasks and questions
    tracker.update_roots_child_status(ChildTaskStatus::InProgress);
    // get the generated questions from the code understanding service
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

    // update the root status to completed
    tracker.update_roots_child_status(ChildTaskStatus::Done);
    // extend the graph with tasks, subtasks, and questions in the task list
    tracker.extend_graph_with_tasklist(&generated_questions);

    let questions_with_ids = tracker.get_questions_with_ids();
    // iter and print 
    for question_id in questions_with_ids.iter() {
        debug!("Question-id {}", question_id);
    }

    let two_questions: Vec<String> = questions_with_ids.iter().take(2).map(|x| x.text.clone()).collect();


    let answers_to_questions =
        match get_code_understandings(request.repo_name.clone(), two_questions).await {
            Ok(answers) => answers,
            Err(e) => {
                log::error!("Failed to get answers to questions: {}", e);
                return Err(e);
            }
        };

    // iterate and print the answers 
    for answer in answers_to_questions.iter() {
        debug!("Answer: \n{}", answer);
    }
    // let code_context_request = CodeUnderstandings {
    //     repo: request.repo_name.clone(),
    //     issue_description: request.user_query.clone(),
    //     qna: answers_to_questions.clone(),
    // };
    // // TODO: Uncomment this once the context generator is implemented
    // // let code_contexts = match get_code_context(code_context_request).await {
    // //     Ok(contexts) => contexts,
    // //     Err(e) => {
    // //         log::error!("Failed to get code contexts: {}", e);
    // //         return Err(e);
    // //     }
    // // };

    Ok(generated_questions)
}

async fn get_generated_questions(
    user_query: String,
    repo_name: String,
) -> Result<TaskList, anyhow::Error> {
    let generate_questions_url = format!("{}/task-list", CONFIG.code_understanding_url);
    let generated_questions = service_caller::<GenerateQuestionRequest, TaskList>(
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
                log::error!("Failed to process question: {}", e.to_string());
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
