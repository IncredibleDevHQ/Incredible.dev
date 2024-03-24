use crate::task_graph::graph_model::{
    ChildTaskStatus, QuestionWithAnswer, QuestionWithId, TrackProcessV1,
};
use crate::task_graph::read_file_data::{
    read_code_understanding_from_file, read_task_list_from_file,
};
use anyhow::{Error, Result};
use common::models::Task;
use futures::future::join_all;
use serde::Serialize;
use std::{collections::HashMap, convert::Infallible};
use tokio::{fs::File, io::AsyncWriteExt};

use common::{
    models::{
        CodeContextRequest, CodeUnderstandRequest, GenerateQuestionRequest, TaskListResponse,
    },
    service_interaction::service_caller,
    CodeUnderstanding, CodeUnderstandings,
};
use common::llm_gateway;
use reqwest::{Method, StatusCode};

use crate::{
    models::{SuggestRequest, SuggestResponse},
    CONFIG,
};
use log::{debug, error, info};

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

async fn handle_suggest_core(request: SuggestRequest) -> Result<impl Serialize, anyhow::Error> {
    // if the request.uuid exists, load the conversation from the conversations API

    let convo_id = request.id;
    match convo_id {
        Some(id) => info!("Conversation ID: {}", id),
        None => info!("No conversation ID provided, New conversation initiated."),
    }
    // initialize the new tracker with task graph
    let mut tracker = TrackProcessV1::new(&request.repo_name, &request.user_query);

    let task_id = tracker.uuid;
    // update the root status to in progress
    tracker.update_roots_child_status(ChildTaskStatus::InProgress);
    // the status is used to track of the processing of its child nodes
    // in this the child elements are tasks, subtasks and questions
    // get the generated questions from the code understanding service
    // call only if DATA_MODE env CONFIG is API
    let generated_questions: TaskListResponse = if CONFIG.data_mode == "api" {
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
        // write to file only if generated_questions.tasks is not None
        if !generated_questions.tasks.is_none() {
            // task is generated successfully, write it to file
            info!("Tasks are generated successfully and writing to file.");
            let mut file = File::create("generated_questions.json").await?;
            file.write_all(serde_json::to_string(&generated_questions)?.as_bytes())
                .await?;
        } else {
            info!("No tasks are generated.");

            if generated_questions.ask_user.is_none() {
                error!("No tasks or either ask_user is generated. The LLM is not supposed to behave this way, test the API response from the code understanding service for query: {}, repo: {}", request.user_query, request.repo_name);
            }
            // No tasks generated because LLM wants more clarification because of vagueness of the issue description from user query
            return Ok(SuggestResponse {
                ask_user: generated_questions.ask_user,
                tasks: generated_questions.tasks,
                questions_with_answers: None,
            });
        }
        generated_questions
    } else {
        // read from the file using the read_task_list_from_file function
        // send meaningful error message if the file is not found
        let generated_questions: Result<TaskListResponse, Error> = read_task_list_from_file("/Users/karthicrao/Documents/GitHub/nezuko/coordinator/sample_generated_data/dataset_1/generated_questions.json").await;
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
    tracker.extend_graph_with_tasklist(&generated_questions.tasks.as_ref().unwrap());

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
                    Ok((answers, None)) // Correctly return a Result wrapping the accumulator tuple.
                }
                Err(e) => {
                    error!("Failed to get answers to questions: {}", e);
                    Err(e) // Directly propagate the error.
                }
            },
        );
        match result {
            Ok((answers, _)) => {
                // If try_fold completed without encountering an error, answers would be populated.
                let mut file = File::create("generated_questions.json").await?;
                file.write_all(serde_json::to_string(&answers)?.as_bytes())
                    .await?;
                Ok(answers)
            }
            Err(e) => {
                // If an error was encountered, it will be returned here.
                Err(e)
            }
        }
    } else {
        // Assuming read_code_understanding_from_file is adjusted to return Vec<Result<QuestionWithAnswer, Error>>
        let code_understand_fie_read_result =
            read_code_understanding_from_file("answers_to_questions.json").await;
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
        return Err(answers_to_questions.err().unwrap());
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

    Ok(SuggestResponse {
        questions_with_answers: Some(answers_to_questions.unwrap()),
        ask_user: generated_questions.ask_user,
        tasks: generated_questions.tasks,
    })
}

async fn get_generated_questions(
    user_query: String,
    repo_name: String,
) -> Result<TaskListResponse, anyhow::Error> {
    // intialize new llm gateway.
    let llm_gateway = llm_gateway::Client::new(&CONFIG.openai_url)
        .temperature(0.0)
        .bearer(CONFIG.openai_api_key.clone())
        .model(&CONFIG.openai_api_key.clone());

    let system_prompt: String = prompts::question_concept_generator_prompt(&user_query, &repo_name);
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
            return Err(anyhow::anyhow!("Unable to fetch response from the gateway"));
        }
    };

    let choices_str = final_response.choices[0]
        .message
        .content
        .clone()
        .unwrap_or_else(|| "".to_string());

    log::debug!("Choices: {}", choices_str);

    let response_task_list: Result<TaskListResponse, serde_json::Error> =
        serde_json::from_str(&choices_str);

    Ok(response_task_list)
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
