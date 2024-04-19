use common::models::TaskList;
use serde::{Deserialize, Serialize};

use common::task_graph::graph_model::QuestionWithAnswer;

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
pub struct SuggestRequest {
    pub id: Option<String>,
    pub user_query: String,
    pub repo_name: String,
}

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
pub struct SuggestResponse {
    // unique identifier for the task
    pub id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    // plan for solving the task.
    pub plan: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub ask_user: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub tasks: Option<TaskList>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub questions_with_answers: Option<Vec<QuestionWithAnswer>>,
}
