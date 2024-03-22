use crate::task_graph::graph_model::{
    ChildTaskStatus, QuestionWithAnswer, QuestionWithId, TrackProcess,
};
use crate::task_graph::read_file_data::{
    read_code_understanding_from_file, read_task_list_from_file,
};
use anyhow::{Error, Result};
use futures::future::join_all;
use std::{collections::HashMap, convert::Infallible};
use tokio::{fs::File, io::AsyncWriteExt};

use common::{
    models::{CodeContextRequest, CodeUnderstandRequest, GenerateQuestionRequest, TaskList},
    service_interaction::service_caller,
    CodeUnderstanding, CodeUnderstandings,
};
use reqwest::{Method, StatusCode};

use crate::{models::SuggestRequest, CONFIG};
use log::{debug, error};

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

async fn handle_suggest_core(
    request: SuggestRequest,
) -> Result<Vec<QuestionWithAnswer>, anyhow::Error> {
    // initialize the new tracker with task graph
    let mut tracker = TrackProcess::new(&request.repo_name, &request.user_query);

    // update root status to in progress
    // the status is used to track of the processing of its child nodes
    // in this the child elelments are tasks, subtasks and questions
    tracker.update_roots_child_status(ChildTaskStatus::InProgress);
    // get the generated questions from the code understanding service
    // call only if DATA_MODE env CONFIG is API
    let generated_questions: TaskList = if CONFIG.data_mode == "api" {
        let generated_questions =
            match get_generated_questions(request.user_query.clone(), request.repo_name.clone())
                .await
            {
                Ok(questions) => questions,
                Err(e) => {
                    log::error!("Failed to generate questions: {}", e);
                    return Err(e);
                }
            };

        // write the generated questions into a file as a json data
        let mut file = File::create("generated_questions.txt").await?;
        file.write_all(serde_json::to_string(&generated_questions)?.as_bytes())
            .await?;
        generated_questions
    } else {
        // read from the file using the read_task_list_from_file function
        // send meaningful error message if the file is not found
        let generated_questions = read_task_list_from_file("/Users/karthicrao/Documents/GitHub/nezuko/coordinator/sample_generated_data/dataset_1/generated_questions.json").await;
        match generated_questions {
            Ok(questions) => questions,
            Err(e) => {
                let err_msg = format!("Failed to read generated questions from file: Check if the path for generated questions and format is correct. Error: {}", e);
                error!("{}", err_msg);
                return Err(anyhow::anyhow!(err_msg));
            }
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

    // Call the API only if the data mode is API
    let answers_to_questions: Result<Vec<QuestionWithAnswer>> = if CONFIG.data_mode == "api" {
        // Retrieve the answers, which are now wrapped in a Vec of Results
        let results = get_code_understandings(request.repo_name.clone(), &questions_with_ids).await;

        let result = results.into_iter().try_fold(
            (Vec::new(), None::<anyhow::Error>),
            |(mut answers, _), result| match result {
                Ok(answer) => {
                    answers.push(answer);
                    Ok((answers, None))  // Correctly return a Result wrapping the accumulator tuple.
                },
                Err(e) => {
                    error!("Failed to get answers to questions: {}", e);
                    Err(e)  // Directly propagate the error.
                },
            },
        );
        match result {
            Ok((answers, _)) => {
                // If try_fold completed without encountering an error, answers would be populated.
                let mut file = File::create("generated_questions.json").await?;
                file.write_all(serde_json::to_string(&answers)?.as_bytes()).await?;
                Ok(answers)
            },
            Err(e) => {
                // If an error was encountered, it will be returned here.
                Err(e)
            },
        }
    } else {
        // Assuming read_code_understanding_from_file is adjusted to return Vec<Result<QuestionWithAnswer, Error>>
        let code_understand_fie_read_result = read_code_understanding_from_file("answers_to_questions.json").await;
        match code_understand_fie_read_result {
            Ok(answers) => Ok(answers),
            Err(e) => {
                let err_msg = format!("Failed to read code understanding from file: Check if the path for code understanding and format is correct. Error: {}", e);
                error!("{}", err_msg);
                return Err(anyhow::anyhow!(err_msg));
            }
        }
    };

    // if there is error return the error the caller
    if answers_to_questions.is_err() {
        return answers_to_questions;
    }

    // unwrap, iterate and print the answers
    for answer in answers_to_questions.as_ref().unwrap().iter() {
        debug!("Answer: {:?}", answer);
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

    answers_to_questions
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

/// Asynchronously retrieves code understandings for a set of questions.
///
/// This function makes concurrent service calls to retrieve code understandings based on
/// provided questions and their associated IDs. It constructs a `QuestionWithAnswer` for
/// each successful response and captures any errors encountered during the process.
///
/// # Arguments
/// * `repo_name` - The name of the repository for which the code understanding is being retrieved.
/// * `generated_questions` - A vector of `QuestionWithIds` containing the questions and their IDs.
///
/// # Returns
/// A vector of `Result<QuestionWithAnswer, Error>` where each entry corresponds to the outcome
/// (success or failure) of retrieving a code understanding for each question.
async fn get_code_understandings(
    repo_name: String,
    generated_questions: &Vec<QuestionWithId>,
) -> Vec<Result<QuestionWithAnswer, Error>> {
    // Construct the URL for the code understanding service.
    let code_understanding_url = format!("{}/retrieve-code", CONFIG.code_understanding_url);

    // Map each question to a future that represents an asynchronous service call
    // to retrieve the code understanding.
    let futures_answers_for_questions: Vec<_> = generated_questions
        .iter()
        .map(|question_with_id| {
            // Clone the URL and repository name for each service call.
            let url = code_understanding_url.clone();
            let repo_name = repo_name.clone();

            // Construct the query parameters for the service call.
            let mut query_params = HashMap::new();
            query_params.insert("query".to_string(), question_with_id.text.clone());
            query_params.insert("repo".to_string(), repo_name);

            // Define an asynchronous block that makes the service call, processes the response,
            // and constructs a `QuestionWithAnswer` object.
            async move {
                // Perform the service call.
                let response: Result<CodeUnderstanding, Error> =
                    service_caller::<CodeUnderstandRequest, CodeUnderstanding>(
                        url,
                        Method::GET,
                        None,
                        Some(query_params),
                    )
                    .await;

                // Convert the service response to a `QuestionWithAnswer`.
                // In case of success, wrap the resulting `QuestionWithAnswer` in `Ok`.
                // In case of an error, convert the error to `anyhow::Error` using `map_err`.
                response
                    .map(|answer| QuestionWithAnswer {
                        question_id: question_with_id.id,
                        question: question_with_id.text.clone(),
                        answer,
                    })
                    .map_err(anyhow::Error::from)
            }
        })
        .collect();

    // Await all futures to complete and collect their results.
    join_all(futures_answers_for_questions).await
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
