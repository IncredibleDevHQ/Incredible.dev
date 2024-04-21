use tokio::sync::mpsc;

use crate::code_understanding::get_codebase_answers_for_questions;
use crate::llm_ops::tasks_questions::generate_tasks_and_questions;
use ai_gateway::message::message::Message;
use anyhow::Result;
use common::models::{
    CodeContextRequest, TaskList, TaskListResponseWithMessage,
};

use crate::controller::error::AgentProcessingError;
use crate::configuration::{
    get_context_generator_url, get_redis_url,
};
use crate::llm_ops::summarize::{
    generate_single_task_summarization_, generate_summarized_answer_for_task,
};
use common::service_interaction::HttpMethod;
use common::task_graph::graph_model::{
    ConversationChain, TrackProcessV1,
};
use common::task_graph::redis::load_task_process_from_redis;
use common::task_graph::state::ConversationProcessingStage;
use log::{debug, error, info};
use reqwest::StatusCode;
use std::convert::Infallible;

use crate::models::SuggestResponse;
use common::{service_interaction::service_caller, CodeUnderstandings};

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
                            match e {
                                AgentProcessingError::LLMRateLimitTriggered => {
                                    debug!("Rate limit triggered, answering one question at a time, stopping processing.");
                                    // return question with answers in suggest response. 
                                    return Ok(SuggestResponse {
                                        id: tracker.get_root_node_uuid().unwrap(),
                                        tasks: Some(tracker.get_current_tasks()?),
                                        questions_with_answers: Some(tracker.get_current_questions_with_answers()?),
                                        plan: None,
                                        ask_user: None,
                                    });
                                }
                                _ => {
                                    debug!("Error: {:?}", e);
                                    // return error 
                                    return Err(anyhow::anyhow!("{}", e));
                                }
                            }

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
