use std::collections::HashMap;

use thiserror::Error; 

use common::{models::CodeUnderstandRequest, service_interaction::{service_caller, HttpMethod}, task_graph::graph_model::{QuestionWithAnswer, QuestionWithId}, CodeUnderstanding};
use futures::future::join_all;
use tokio::sync::mpsc;

use crate::{configuration::get_code_understanding_url, controller::error::AgentProcessingError};

// Asynchronously retrieves answers for a set of questions from a codebase,
// optionally in parallel, and immediately tries to save each answer to Redis as it is received.
pub async fn get_codebase_answers_for_questions(
    repo_name: String,
    task_id: String,
    generated_questions: &[QuestionWithId],
    parallel: bool,
    tx: mpsc::Sender<Result<QuestionWithAnswer, AgentProcessingError>>,
    can_interrupt: bool,
) ->  Result<(), AgentProcessingError> {
    let code_understanding_url = format!("{}/retrieve-code", get_code_understanding_url());

    if parallel {
        // Parallel processing
        join_all(generated_questions.iter().map(|question_with_id| {
            let url = code_understanding_url.clone();
            let repo = repo_name.clone();
            let task_id = task_id.clone();
            let tx = tx.clone();
            async move {
                let result = handle_question(url, repo, question_with_id, task_id).await;
                tx.send(result)
                    .await
                    .expect("Failed to send result to channel");
            }
        }))
        .await;
    } else {
        // Sequential processing, potentially ending early on error
        for question_with_id in generated_questions {
            let result = handle_question(
                code_understanding_url.clone(),
                repo_name.clone(),
                question_with_id,
                task_id.clone(),
            )
            .await;
            tx.send(result)
                .await
                .expect("Failed to send result to channel");

            // if there was only one question to process and the process can be interrupted, return early
            if generated_questions.len() == 1 && can_interrupt {
                return Ok(());
            }
            if can_interrupt {
                let err_result = Err(AgentProcessingError::LLMRateLimitTriggered.into());
                tx.send(err_result).await.expect("Failed to send result to channel");
                return Err(AgentProcessingError::LLMRateLimitTriggered);
            }
        }
    }

    Ok(())
}

async fn handle_question(
    url: String,
    repo_name: String,
    question_with_id: &QuestionWithId,
    task_id: String,
) -> Result<QuestionWithAnswer, AgentProcessingError> {
    let mut query_params = HashMap::new();
    query_params.insert("query".to_string(), question_with_id.text.clone());
    query_params.insert("repo".to_string(), repo_name);
    query_params.insert("question_id".to_string(), question_with_id.id.to_string());
    query_params.insert("task_id".to_string(), task_id.to_string());

    let response = service_caller::<CodeUnderstandRequest, CodeUnderstanding>(
        url,
        HttpMethod::GET,
        None,
        Some(query_params),
    ).await;

    // Call the code understanding service and map the response
    response
        .map(|answer| QuestionWithAnswer {
            question_id: question_with_id.id,
            question: question_with_id.text.clone(),
            answer,
        })
        .map_err(AgentProcessingError::from)
    // send a dummy answer
    // Ok(QuestionWithAnswer{
    //     question_id: question_with_id.id,
    //     question: question_with_id.text.clone(),
    //     answer: CodeUnderstanding {
    //         context: vec![],
    //         question: question_with_id.text.clone(),
    //         answer: "Dummy answer".to_string(),
    //     }
    // })
}