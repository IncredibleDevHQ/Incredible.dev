use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
pub struct SuggestRequest {
    pub user_query: String,
    pub repo_name: String,
}
