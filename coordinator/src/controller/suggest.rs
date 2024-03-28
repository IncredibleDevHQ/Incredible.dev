use anyhow::{Error, Result};
use common::llm_gateway::api::{Message, Messages};
use common::models::{
    CodeContextRequest, CodeUnderstandRequest, TaskList, TaskListResponseWithMessage,
};
use futures::future::join_all;
use log::{debug, error, info};
use reqwest::{Method, StatusCode};
use std::{collections::HashMap, convert::Infallible};

use crate::models::SuggestResponse;
use crate::task_graph::graph_model::{
    ConversationChain, QuestionWithAnswer, QuestionWithId, TrackProcessV1,
};
use crate::task_graph::redis::load_task_process_from_redis;
use crate::task_graph::state::ConversationProcessingStage;
use common::{llm_gateway, prompts};
use common::{service_interaction::service_caller, CodeUnderstanding, CodeUnderstandings};

use crate::{models::SuggestRequest, CONFIG};

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

async fn handle_suggest_core(request: SuggestRequest) -> Result<SuggestResponse, anyhow::Error> {
    // if the request.uuid exists, load the conversation from the conversations API
    let convo_id = request.id;
    let mut tracker = if convo_id.is_some() {
        let uuid = convo_id.clone().unwrap();
        info!(
            "Conversation ID exists, loading the conversation from Redis: {}",
            uuid
        );
        // load the conversation from the redis
        let tracker = load_task_process_from_redis(&uuid);
        // return error if there is error loading the conversation
        if tracker.is_err() {
            let err_msg = format!(
                "Failed to load the conversation from Redis: {}",
                tracker.err().unwrap()
            );
            error!("{}", err_msg);
            return Err(anyhow::anyhow!("{}", err_msg));
        }
        tracker.unwrap()
    } else {
        info!("No conversation ID provided, New conversation initiated.");
        // create a new tracker
        TrackProcessV1::new(&request.repo_name)
    };
    // get the state of the conversation
    let (mut state, node_index) = tracker.last_conversation_processing_stage();

    loop {
        match state {
            ConversationProcessingStage::OnlyRootNodeExists => {
                error!("Only root node exists, no conversation has happened yet. Invalid state, create new conversation");
                return Err(anyhow::anyhow!("Only root node exists, no conversation has happened yet. Invalid state, create new conversation"));
            }
            ConversationProcessingStage::GraphNotInitialized => {
                debug!("Graph not initialized, initializing the graph and setting the next state to GenerateTasksAndQuestions");
                tracker.initialize_graph();
                state = ConversationProcessingStage::GenerateTasksAndQuestions;
            }
            ConversationProcessingStage::GenerateTasksAndQuestions => {
                // get the generated questions from the LLM or the file based on the data modes
                let generated_questions_with_llm_messages: TaskListResponseWithMessage =
                    generate_tasks_and_questions(
                        request.user_query.clone(),
                        request.repo_name.clone(),
                    )
                    .await?;

                debug!(
                    "Generated questions: {:?}",
                    generated_questions_with_llm_messages
                );

                // the response contains the generated questions and the messages
                // the messages contain the system prompt which was used to generate the questions
                // also the response of the assistant for the prompt used to generate questions.
                let generated_questions: TaskList = generated_questions_with_llm_messages.task_list;
                let messages = generated_questions_with_llm_messages.messages;

                if generated_questions.ask_user.is_none() && generated_questions.tasks.is_none() {
                    let error_message = format!(
                        "No tasks or either ask_user is generated. The LLM is not supposed to behave this way, test the API response from the code understanding service for query: {}, repo: {}",
                        request.user_query, request.repo_name
                    );
                    error!("{}", error_message);
                    return Err(anyhow::anyhow!(error_message));
                }

                let user_system_assistant_conversation = ConversationChain {
                    user_message: Message::user(&request.user_query),
                    system_message: messages[0].clone(),
                    assistant_message: messages[1].clone(),
                };
                // add the generated questions to the graph
                // if the questions are not present, return the ask_user message
                // the function also saves the graph to the redis
                // Note: this mutates the state of graph inside task process
                tracker.extend_graph_with_conversation_and_tasklist(
                    user_system_assistant_conversation,
                    Some(TaskList {
                        tasks: generated_questions.tasks.clone(),
                        ask_user: None,
                    }),
                )?;

                // when you ask LLM to generate tasks, subtasks and questions, it might not generate it
                // when the user hasen't provided enough context.
                // for instance, if user asks something like "help me with my api",
                // the LLM might respond with a generic response with some detail like "Can you provide more context? What specifically do you need help with regarding your API?"
                // In this case the the systems state in the graph would transition to AwaitingUserInput
                // if you don't stop here and dry to fetch answer again, the state machine will loop forever.
                // Instead you return and provide more opporunity for user to provide input.
                (state, _) = tracker.last_conversation_processing_stage();
                if state == ConversationProcessingStage::AwaitingUserInput {
                    debug!("Tasks and Questions not generated, awaiting more user input, returning ask_user state.");
                    // return TaskList
                    return Ok(SuggestResponse {
                        tasks: None,
                        ask_user: generated_questions.ask_user.clone(),
                        questions_with_answers: None,
                    });
                }
                // the tasks and questions are successfullly generated, move to find answers for the questions.
                debug!("Tasks and Questions generated successfully, moving onto finding answers for the generated questions.");
                state = ConversationProcessingStage::TasksAndQuestionsGenerated;
            }
            ConversationProcessingStage::TasksAndQuestionsGenerated => {
                debug!("Tasks and questions are generated, moving onto finding answers for the questions.");
                // return the tasks, subtasks and questions.
                let task_list = tracker.get_unanswered_questions()?;
                debug!(
                    "Unanswered questions fetched from task_graph: {:?}",
                    task_list
                );
                // print the graph
                //tracker.print_graph_hierarchy();
                let questions_with_answers = get_codebase_answers_for_questions(
                    request.repo_name.clone(),
                    &task_list.clone(),
                )
                .await;
                // update the graph with answers
                // Note: this mutates the state of graph inside task process
                tracker.extend_graph_with_answers(&questions_with_answers)?;
                // find if any of the Result in Vec has error, if so just return the error
                // the reason to do this is to avoid the state machine getting into an infinite loop.
                // Imagine a scenario where there were some unanswered questions,
                // we don't want the system to continue further until they succeed.
                // So we update the task graph even if there some successfull answers, and return error
                // even if there was one unsuccessful answer.
                // the client can retry, and the next time the system will contine from where it left off
                // to retry fetching answer only for the unanswered questions.
                let answer_err = questions_with_answers.iter().find(|x| x.is_err());
                if let Some(err_result) = answer_err {
                    return Err(anyhow::anyhow!(err_result.as_ref().unwrap_err().to_string()));
                } else {
                    let answers = questions_with_answers
                        .into_iter()
                        .map(|x| x.unwrap())
                        .collect::<Vec<_>>();
                    return Ok(SuggestResponse {
                        tasks: Some(tracker.get_current_tasks()?),
                        questions_with_answers: Some(answers),
                        ask_user: None,
                    });
                }
            }
            // you start with this state because the previous conversation with the user ended
            // abruply since the user didn't provide enough context.
            // So you regenerate tasks and questions to continue the conversation.
            ConversationProcessingStage::AwaitingUserInput => {
                debug!("Awaiting user input, moving onto getting tasks/questions for the next objective round.");
                state = ConversationProcessingStage::GenerateTasksAndQuestions;
                //tracker.print_graph_hierarchy();
            }
            ConversationProcessingStage::Unknown => {
                // return error
                let err_msg = "Unknown graph state, aborting the conversation.";
                error!("{}", err_msg);
                return Err(anyhow::anyhow!("{}", err_msg));
            }
            ConversationProcessingStage::AllQuestionsAnswered => {
                debug!("All questions are answered, nothing left to do, returning the result from the task graph");
                return Ok(SuggestResponse {
                    tasks: Some(tracker.get_current_tasks()?),
                    questions_with_answers: Some(tracker.get_current_questions_with_answers()?),
                    ask_user: None,
                });
            }
            ConversationProcessingStage::QuestionsPartiallyAnswered => {
                debug!("Some Questions are unanswered, continuing to find answers.");
                state = ConversationProcessingStage::TasksAndQuestionsGenerated;
            }
        }
    }
}

async fn generate_tasks_and_questions(
    user_query: String,
    repo_name: String,
) -> Result<TaskListResponseWithMessage, anyhow::Error> {
    // initialize new llm gateway.

    // otherwise call the llm gateway to generate the questions
    let llm_gateway = llm_gateway::Client::new(&CONFIG.openai_url)
        .temperature(0.0)
        .bearer(CONFIG.openai_api_key.clone())
        .model(&CONFIG.openai_api_key.clone());

    let system_prompt: String = prompts::question_concept_generator_prompt(&user_query, &repo_name);
    let system_message = llm_gateway::api::Message::system(&system_prompt);
    // append the system message to the message history
    let mut messages = Some(system_message.clone()).into_iter().collect::<Vec<_>>();

    // append the system message to the message history

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

    //log::debug!("Choices: {}", choices_str);

    let response_task_list: Result<TaskList, serde_json::Error> =
        serde_json::from_str(&choices_str);

    match response_task_list {
        Ok(task_list) => {
            //log::debug!("Task list: {:?}", task_list);
            Ok(TaskListResponseWithMessage {
                task_list: task_list,
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
async fn get_codebase_answers_for_questions(
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
