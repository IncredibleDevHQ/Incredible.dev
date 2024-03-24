use common::models::TaskList;
use serde::{Deserialize, Serialize};

use crate::task_graph::graph_model::QuestionWithAnswer;

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
pub struct SuggestRequest {
    pub id: Option<uuid::Uuid>,
    pub user_query: String,
    pub repo_name: String,
}


#[derive(Clone, Debug, Default, Deserialize, Serialize)]
pub struct SuggestResponse {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub ask_user: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub tasks: Option<TaskList>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub questions_with_answers: Option<Vec<QuestionWithAnswer>>,
}
