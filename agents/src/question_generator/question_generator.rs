use openai::model::Model;
use openai::OpenAI;
use regex::Regex;
use serde_json::json;

const MODEL_3_4K: &str = "model_3_4K";

pub async fn query_transformer(query: &str, namespace: &str) -> Vec<String> {
    let repo_name = namespace.split("/").last().unwrap_or("");

    println!("namespace: {}", namespace);
    println!("repoName: {}", repo_name);

    let message_content = json![
        {
            "role": "system",
            "content": "
            
            You are a QueryTransformer that take query and update it with three new query so that better semantic search can be performed. 
            
            Your job is to perform the following tasks:
            - Update Query but updated query should hold same meaning, but potentially using different keywords or phrasing.
            - if the query is something like \"what is the repo about\" or related  transform it to  \"what is ${repo_name}\"
            - DO NOT CHANGE MEANING OF THE QUERY
            - QUESTION LIKE WHAT IS THIS REPO ABOUT OR TELL ME ABOUT THIS CODE BASE SEND OUT readme    
            - RETURN ARRAY CONTAINING THREE UPDATED QUERIES 
            
            ----Example start----
            
            query- how get conversation is implemented
            
            response- [\"what is get conversation\", \"how get conversation is implemented in code\", \"get conversation implementation?\"]

            ----Example end----
            
            GIVE ONLY ARRAY  containing three updated queries.

            DO NOT give queries in number, like 1. \"How are conversation routes implemented?\" 2. \"What is the implementation process for conversation routes?\" 3. \"Can you explain the implementation of conversation routes?\"

            ,"
        },
        {
            "role": "user",
            "content": format!("this the query '{}' , Update it ", query)
        }
    ];
}
