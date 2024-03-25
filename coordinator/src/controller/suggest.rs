use anyhow::{Error, Result};
use futures::future::join_all;
use log::{debug, error, info};
use reqwest::{Method, StatusCode};
use serde::Serialize;
use std::{collections::HashMap, convert::Infallible};
use tokio::{fs::File, io::AsyncWriteExt};

use crate::task_graph::graph_model::{QuestionWithAnswer, QuestionWithId, TrackProcessV1};
use crate::task_graph::read_file_data::{
    read_code_understanding_from_file, read_task_list_from_file,
};
use crate::task_graph::state::ConversationProcessingStage;
use common::{llm_gateway, prompts};
use common::{
    models::{
        CodeContextRequest, CodeUnderstandRequest, TaskListResponse, TaskListResponseWithMessage,
    },
    service_interaction::service_caller,
    CodeUnderstanding, CodeUnderstandings,
};

use crate::{
    models::{SuggestRequest, SuggestResponse},
    CONFIG,
};

use crate::task_graph::redis::{load_task_process_from_redis, save_task_process_to_redis};
pub const ANSWER_MODEL: &str = "gpt-4-0613";

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
    let (tracker, node_id) = if convo_id.is_some() {
        info!(
            "Conversation ID exists, loading the conversation from Redis: {}",
            convo_id.unwrap()
        );
        // load the conversation from the redis
        let mut tracker = load_task_process_from_redis(convo_id.unwrap()).await;
        // return error if there is error loading the conversation
        if tracker.is_err() {
            error!(
                "Failed to load the conversation from Redis: {}",
                tracker.err().unwrap()
            );
            return Err(tracker.err().unwrap());
        }
        let mut tracker_graph: TrackProcessV1 = tracker.as_mut().unwrap();
        // find the last conversation state and get the last conversation node ID from the conversation graph
        let (last_processing_stage, node_id) = tracker_graph.last_conversation_processing_stage();
        // return error if there the last conversation state is unknown or the node id is none
        if (last_processing_stage == ConversationProcessingStage::Unknown) || node_id.is_none() {
            error!("Failed to find the last conversation state from the conversation graph, initiate a new conversation");
            return Err(anyhow::anyhow!("Failed to find the last conversation state from the conversation graph, initiate a new conversation"));
        }

        let last_conversation_node_id = node_id.unwrap();
        (tracker_graph, last_conversation_node_id)
    } else {
        info!("No conversation ID provided, New conversation initiated.");
        // create a new tracker

        let mut tracker = TrackProcessV1::new(&request.repo_name, &request.user_query);
        // return tracker and the new conversation node ID
        let node_id = tracker.uuid;
    };


    // get the generated questions from the LLM or the file based on the data modes
    let generated_questions_with_llm_messages = match get_generated_questions(
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

    debug!(
        "Generated questions: {:?}",
        generated_questions_with_llm_messages
    );

    // the response contains the generated questions and the messages
    // the messages contain the system prompt which was used to generate the questions
    // also the response of the assistant for the prompt used to generate questions.
    let generated_questions = generated_questions_with_llm_messages.task_list_response;
    let messages = generated_questions_with_llm_messages.messages;

    if generated_questions.ask_user.is_none() && generated_questions.tasks.is_none() {
        error!("No tasks or either ask_user is generated. The LLM is not supposed to behave this way, test the API response from the code understanding service for query: {}, repo: {}",
                 request.user_query, request.repo_name);
        return Err(anyhow::anyhow!("No tasks or either ask_user is generated. The LLM is not supposed to behave this way, test the API response from the code understanding service for query: {}, repo: {}",
                 request.user_query, request.repo_name));
    }

    // add the generated questions to the graph
    // if the questions are not present, return the ask_user message
    // the function also saves the graph to the redis
    let does_task_exist =
        tracker.extend_graph_with_tasklist(generated_questions.clone(), messages[0], messages[1]);

    // return error if Result is Err
    if does_task_exist.is_err() {
        error!(
            "Failed to extend graph with tasklist: {}",
            does_task_exist.err().unwrap()
        );
        return Err(does_task_exist.err().unwrap());
    }

    // if task does not exist, return the ask_user message
    if !does_task_exist.unwrap() {
        info!("No tasks found in the response, returning the ask_user message");
        return Ok(SuggestResponse {
            questions_with_answers: None,
            ask_user: generated_questions.ask_user,
            tasks: generated_questions.tasks,
        });
    }

    let questions_with_ids = tracker.get_questions_with_ids();
    // iter and print
    for question_id in questions_with_ids.iter() {
        debug!("Question-id {}", question_id);
    }

    // Call the API only if the data mode is API
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
) -> Result<TaskListResponseWithMessage, anyhow::Error> {
    // intialize new llm gateway.

    // if data mode is file, read the data from the file
    if CONFIG.data_mode == "file" {
        return read_task_list_from_file("task_list.json".to_string()).await;
    }

    // otherwise call the llm gateway to generate the questions
    let llm_gateway = llm_gateway::Client::new(&CONFIG.openai_url)
        .temperature(0.0)
        .bearer(CONFIG.openai_api_key.clone())
        .model(&CONFIG.openai_api_key.clone());

    let system_prompt: String = prompts::question_concept_generator_prompt(&user_query, &repo_name);
    let system_message = llm_gateway::api::Message::system(&system_prompt);
    let mut messages = Some(system_message).into_iter().collect::<Vec<_>>();

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

    // create assistant message and add it to the messages
    let assistant_message = llm_gateway::api::Message::assistant(&choices_str);
    messages.push(assistant_message);

    log::debug!("Choices: {}", choices_str);

    let response_task_list: Result<TaskListResponse, serde_json::Error> =
        serde_json::from_str(&choices_str);

    match response_task_list {
        Ok(task_list) => {
            log::debug!("Task list: {:?}", task_list);
            Ok(TaskListResponseWithMessage {
                task_list_response: task_list,
                messages,
            })
        }
        Err(e) => {
            error!("Failed to parse response from the gateway: {}", e);
            Err(anyhow::anyhow!(
                "Failed to parse response from the gateway: {}",
                e
            ))
        }
    }
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
