use crate::configuration::{
    get_code_search_url, get_code_understanding_url, get_context_generator_url, get_redis_url,
};
use crate::llm_ops::summarize::{
    generate_single_task_summarization_, generate_summarized_answer_for_task,
};
use tokio::sync::mpsc;
use tokio::task;
use warp::reject::PayloadTooLarge;

use crate::llm_ops::tasks_questions::generate_tasks_and_questions;
use ai_gateway::message::message::Message;
use anyhow::{anyhow, Error, Result};
use common::models::{
    CodeContextRequest, CodeUnderstandRequest, TaskList, TaskListResponseWithMessage,
};

use common::service_interaction::HttpMethod;
use common::task_graph::graph_model::{
    ConversationChain, QuestionWithAnswer, QuestionWithId, TrackProcessV1,
};
use common::task_graph::redis::load_task_process_from_redis;
use common::task_graph::state::ConversationProcessingStage;
use futures::future::join_all;
use log::{debug, error, info};
use reqwest::{Method, StatusCode};
use std::{collections::HashMap, convert::Infallible};

use crate::models::SuggestResponse;
use common::{service_interaction::service_caller, CodeUnderstanding, CodeUnderstandings};

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

async fn handle_suggest_core(request: SuggestRequest) -> Result<SuggestResponse, anyhow::Error> {
    // if the request.uuid exists, load the conversation from the conversations API
    let convo_id = request.id;

    let redis_url: &str = &get_redis_url();
    let mut tracker = if convo_id.is_some() {
        let uuid = convo_id.clone().unwrap();
        info!(
            "Conversation ID exists, loading the conversation from Redis: {}",
            uuid
        );

        // load the conversation from the redis
        let tracker = load_task_process_from_redis(redis_url, &uuid);
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
        TrackProcessV1::new(&request.repo_name, redis_url)
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
                &tracker.initialize_graph();
                state = ConversationProcessingStage::GenerateTasksAndQuestions;
            }
            ConversationProcessingStage::GenerateTasksAndQuestions => {
                // get the generated questions from the LLM or the file based on the data modes
                let generated_questions_with_llm_messages: TaskListResponseWithMessage =
                    generate_tasks_and_questions(&request.user_query, &request.repo_name).await?;

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
                // when the user hasn't provided enough context.
                // for instance, if user asks something like "help me with my api",
                // the LLM might respond with a generic response with some detail like "Can you provide more context? What specifically do you need help with regarding your API?"
                // In this case the the systems state in the graph would transition to AwaitingUserInput
                // if you don't stop here and dry to fetch answer again, the state machine will loop forever.
                // Instead you return and provide more opportunity for user to provide input.
                (state, _) = tracker.last_conversation_processing_stage();
                if state == ConversationProcessingStage::AwaitingUserInput {
                    debug!("Tasks and Questions not generated, awaiting more user input, returning ask_user state.");
                    // return TaskList
                    return Ok(SuggestResponse {
                        id: tracker.get_root_node_uuid().unwrap(),
                        tasks: None,
                        plan: None,
                        ask_user: generated_questions.ask_user.clone(),
                        questions_with_answers: None,
                    });
                }
                // the tasks and questions are successfully generated, move to find answers for the questions.
                debug!("Tasks and Questions generated successfully, moving onto finding answers for the generated questions.");
                state = ConversationProcessingStage::TasksAndQuestionsGenerated;
            }
            ConversationProcessingStage::TasksAndQuestionsGenerated => {
                debug!("Tasks and questions are generated, moving onto finding answers for the questions.");
                tracker.print_graph_hierarchy();
                // return the tasks, subtasks and questions.
                let questions_list = tracker.get_unanswered_questions()?;
                debug!(
                    "Unanswered questions fetched from task_graph: {:?}",
                    questions_list
                );
                let (tx, mut rx) = mpsc::channel(2);
                // print the graph
                let question_count = questions_list.len();
                let repo_name = request.repo_name.clone();
                let task_id = tracker.get_root_node_uuid().unwrap();
                let handle = tokio::spawn(async move {
                    if let Err(e) = get_codebase_answers_for_questions(
                        repo_name,
                        task_id,
                        &questions_list,
                        false,
                        tx,
                        true,
                    )
                    .await
                    {
                        log::error!("Error processing questions: {:?}", e);
                    }
                });

                // Collect answers
                let mut answers = Vec::new();
                while let Some(result) = rx.recv().await {
                    match result {
                        Ok(answer) => {
                            debug!("Received answer: {:?}", answer);
                            // save the answer to the graph
                            tracker.extend_graph_with_answers(&vec![Ok(answer.clone())])?;
                            answers.push(answer);
                        }
                        Err(e) => {
                            log::error!("Error received: {:?}", e);
                            if answers.len() != question_count {
                                debug!("Error: Received answers count does not match the questions count.");
                                return Err(anyhow!(
                                    "Received answers count does not match the questions count."
                                ));
                            }
                            break; // Stop processing on error if needed
                        }
                    }
                }

                // Wait for all processing to complete
                handle.await?;
                state = ConversationProcessingStage::AllQuestionsAnswered;
            }
            // you start with this state because the previous conversation with the user ended
            // abruptly since the user didn't provide enough context.
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
                debug!("All questions are answered, Summarizing the answers.");
                state = ConversationProcessingStage::SummarizeAnswers;
            }
            // Summarize answers after all the answers are fetched.
            ConversationProcessingStage::SummarizeAnswers => {
                debug!("Summarizing answers for the tasks and questions.");
                let tasks_qna_context = tracker.collect_tasks_questions_answers_contexts()?;

                let summary = generate_summarized_answer_for_task(
                    request.user_query.clone(),
                    &tasks_qna_context,
                )
                .await?;

                // connect the summary to the graph, this will also save the summary to the redis.
                tracker.connect_task_to_answer_summary(&tasks_qna_context, &summary)?;

                return Ok(SuggestResponse {
                    id: tracker.get_root_node_uuid().unwrap(),
                    plan: Some(summary),
                    tasks: Some(tracker.get_current_tasks()?),
                    questions_with_answers: Some(tracker.get_current_questions_with_answers()?),
                    ask_user: None,
                });
            }
            ConversationProcessingStage::QuestionsPartiallyAnswered => {
                debug!("Some Questions are unanswered, continuing to find answers.");
                state = ConversationProcessingStage::TasksAndQuestionsGenerated;
            }

            ConversationProcessingStage::AnswersSummarized => {
                tracker.print_graph_hierarchy();
                // nothing more to do,return the answers.
                debug!("All answers summarized, nothing to do!");
                // let tasks_qna_context = tracker.collect_tasks_questions_answers_contexts()?;

                // for task in &tasks_qna_context.tasks {
                //     debug!("Code Context: {:?}", task.merged_code_contexts);
                // }

                // let tasks_qna_context = tracker.collect_tasks_questions_answers_contexts()?;

                // let code_search_url = get_code_search_url();
                // for task in &tasks_qna_context.tasks {
                //     // call generate_single_task_summarization function to generate the summary for each task.
                // generate_single_task_summarization_(
                //     &request.user_query.clone(),
                //     &code_search_url,
                //     &tasks_qna_context.tasks[1].clone(),
                // )
                // .await?;
                // }

                // let summary = generate_summarized_answer_for_task(
                //     request.user_query.clone(),
                //     &tasks_qna_context,
                // )
                // .await?;

                // connect the summary to the graph, this will also save the summary to the redis.
                //tracker.connect_task_to_answer_summary(&tasks_qna_context, summary)?;
                let plan = tracker.get_summary()?;
                return Ok(SuggestResponse {
                    id: tracker.get_root_node_uuid().unwrap(),
                    tasks: Some(tracker.get_current_tasks()?),
                    questions_with_answers: Some(tracker.get_current_questions_with_answers()?),
                    plan: Some(plan),
                    ask_user: None,
                });
            }
        }
    }
}

// Asynchronously retrieves answers for a set of questions from a codebase,
// optionally in parallel, and immediately tries to save each answer to Redis as it is received.

async fn get_codebase_answers_for_questions(
    repo_name: String,
    task_id: String,
    generated_questions: &[QuestionWithId],
    parallel: bool,
    tx: mpsc::Sender<Result<QuestionWithAnswer, Error>>,
    can_interrupt: bool,
) -> Result<()> {
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
                let err_result = Err(anyhow!("Interrupted, processed just one question"));
                tx.send(err_result)
                    .await
                    .expect("Failed to send result to channel");
                return Err(anyhow!("Interrupted, processed just one question"));
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
) -> Result<QuestionWithAnswer, Error> {
    let mut query_params = HashMap::new();
    query_params.insert("query".to_string(), question_with_id.text.clone());
    query_params.insert("repo".to_string(), repo_name);
    query_params.insert("question_id".to_string(), question_with_id.id.to_string());
    query_params.insert("task_id".to_string(), task_id.to_string());

    // Call the code understanding service and map the response
    service_caller::<CodeUnderstandRequest, CodeUnderstanding>(
        url,
        HttpMethod::GET,
        None,
        Some(query_params),
    )
    .await
    .map(|answer| QuestionWithAnswer {
        question_id: question_with_id.id,
        question: question_with_id.text.clone(),
        answer,
    })
    .map_err(anyhow::Error::from)
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
// TODO: Remove unused warning suppressor once the context generator is implemented
#[allow(unused)]
async fn get_code_context(code_understanding: CodeUnderstandings) -> Result<String, anyhow::Error> {
    let context_generator_url = get_context_generator_url();
    let code_context_url = format!("{}/find-code-context", context_generator_url);
    let code_context = service_caller::<CodeContextRequest, String>(
        code_context_url,
        HttpMethod::POST,
        Some(CodeContextRequest {
            qna_context: code_understanding.clone(),
        }),
        None,
    )
    .await?;

    Ok(code_context)
}
