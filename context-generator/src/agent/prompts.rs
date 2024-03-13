use crate::routes::RetrieveCodeRequest;
use std::future::Future;
use std::pin::Pin;

use std::sync::Arc;

extern crate common;

use common::prompt_string_generator::GeneratePromptString;
use common::service_interaction::fetch_code_span;
use common::CodeSpanRequest;

pub struct RetrieveCodeRequestWithUrl {
    pub url: String,
    pub request_data: RetrieveCodeRequest,
}

// Implementing GeneratePromptString for RetrieveCodeRequestWithUrl to generate prompts asynchronously.
impl GeneratePromptString for RetrieveCodeRequestWithUrl {
    // Asynchronously generate a prompt based on request data.
    // Returns a future resolving to either the generated prompt string or an error.
    fn generate_prompt(
        &self,
        url: String,
    ) -> Pin<Box<dyn Future<Output = Result<String, Box<dyn std::error::Error + Send>>> + Send>> {
        // Clone necessary data to move into the async block.
        let url_arc = Arc::new(self.url.clone());
        let qna_context_clone = self.request_data.qna_context.clone();

        // The async block generates the prompt, returning a Future.
        Box::pin(async move {
            // Introduction for the prompt, including the issue description and repository.
            let intro = format!(
                "Here is the issue described by the user from the repository '{}':\n'{}'\nHere are some interesting facts in the form of question and answer and their corresponding code context to help you identify relevant code snippets to solve the problem:\n",
                qna_context_clone.repo, qna_context_clone.issue_description
            );

            // Transform each QnA into a future that fetches and formats code spans.
            let fetches = qna_context_clone.qna.into_iter().map(move |qna| {
                let question_arc = Arc::new(qna.question);
                let answer_arc = Arc::new(qna.answer);
                let url_arc = Arc::clone(&url_arc);

                // Process each code context within a QnA.
                qna.context.into_iter().map(move |context| {
                    let url_clone = Arc::clone(&url_arc);
                    let question_clone = Arc::clone(&question_arc);
                    let answer_clone = Arc::clone(&answer_arc);

                    // Construct the request for code spans.
                    let request = CodeSpanRequest {
                        repo: context.repo.clone(),
                        branch: context.branch.clone(),
                        path: context.path.clone(),
                        ranges: Some(context.ranges),
                        id: None,
                    };

                    // Asynchronously fetch and format each code chunk.
                    async move {
                        let code_chunks = fetch_code_span(url_clone.to_string(), request).await?;
                        let mut formatted_code = String::new();

                        // Concatenate all code chunks into a single formatted string.
                        for chunk in code_chunks {
                            formatted_code.push_str(&format!("Code:\n{}\n", chunk.to_string()));
                        }

                        // Combine question, answer, and formatted code into the final output.
                        Ok(format!(
                            "Question: {}\nAnswer: {}\n{}\n",
                            question_clone.as_str(),
                            answer_clone.as_str(),
                            formatted_code
                        ))
                    }
                })
            }).flatten().collect::<Vec<_>>();

            // Await all fetch and format operations, combining successful results.
            match futures::future::try_join_all(fetches).await {
                Ok(results) => Ok(intro + &results.concat()),  // Prepend the intro to the concatenated results.
                Err(e) => Err(e),  // Return the first encountered error.
            }
        })
    }
}


pub fn functions_new(add_proc: bool) -> serde_json::Value {
    let mut funcs = serde_json::json!(
        [
            {
                "name": "expand",
                "description": "Request more context or detailed definitions within the codebase to enhance understanding or preparation for potential code modifications. Used to extend the code's scope or fetch definitions of functions, classes, or other types.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "scope_expansion": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 5,
                            "items": {
                                "type": "object",
                                "properties": {
                                    "file": {
                                        "type": "string",
                                        "description": "The file path requiring context expansion."
                                    },
                                    "range": {
                                        "type": "array",
                                        "items": {
                                            "type": "integer"
                                        },
                                        "minItems": 1,
                                        "maxItems": 5,
                                        "description": "The line number range (start, end) to expand within the file."
                                    }
                                },
                                "required": ["file", "range"]
                            },
                            "description": "Specifies the file and range to broaden the code context."
                        },
                        "def_expansion": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 5,
                            "items": {
                                "type": "object",
                                "properties": {
                                    "file": {
                                        "type": "string",
                                        "description": "The file path containing the definition to expand."
                                    },
                                    "name": {
                                        "type": "string",
                                        "description": "The name of the definition or function to be detailed."
                                    },
                                    "line": {
                                        "type": "integer",
                                        "description": "The line number where the definition or function is most relevant."
                                    }
                                },
                                "required": ["file", "name", "line"]
                            },
                            "description": "Provides details for fetching in-depth information about specific code elements."
                        }
                    },
                    "required": ["scope_expansion", "def_expansion"]
                }
            },
            {
                "name": "range",
                "description": "Identify significant code ranges to pinpoint areas relevant to the user's query. Essential for locating critical segments within the code.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Keywords or descriptions to help identify relevant code sections, such as specific functionality or components."
                        }
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "none",
                "description": "Conclude the analysis process when all required information has been gathered, signifying no further data retrieval or analysis is needed.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message": {
                            "type": "string",
                            "description": "A concluding message or summary based on the gathered data, indicating the completion of the analysis and readiness for potential code modifications."
                        }
                    },
                    "required": ["message"]
                }
            },
        ]
    );
    funcs
}

// new system prompt
pub fn new_system_prompt_v2<'a>(paths: impl IntoIterator<Item = &'a str>) -> String {
    let mut s = "".to_string();

    let mut paths = paths.into_iter().peekable();

    if paths.peek().is_some() {
        s.push_str("## PATHS ##\nindex, path\n");
        for (i, path) in paths.enumerate() {
            s.push_str(&format!("{}, {}\n", i, path));
        }
        s.push('\n');
    }

    s.push_str(
        r#"
        Your primary role is to assist in identifying relevant sections within a codebase that can inform and facilitate potential code modifications to meet the user's objectives. By carefully analyzing user queries, your task is to pinpoint critical code segments that are pertinent to the issue at hand. Utilize function.expand to request more context or detailed definitions of functions, classes, or other types, enhancing understanding and preparation for modification. Employ function.range to precisely locate these relevant code sections. When you have gathered sufficient information for a developer to act upon, conclude your analysis with function.none. Follow these detailed guidelines to ensure a focused and effective approach:

        1. **General Guidelines**:
           - ALWAYS call a function (`function.expand` or `function.range`), DO NOT answer the question directly, even if the query is not in English.
           - DO NOT call the same function with identical arguments within the same session.
           - DO NOT make assumptions about the structure of the codebase or the existence of specific files or folders.
           - If the output of a function does not address the query effectively, adjust the arguments and try again or switch to the other function as needed.
           - ALWAYS call a function. DO NOT provide direct answers without leveraging the functionalities of `function.expand` and `function.range`.
        
        2. **Using `function.expand` with Parameters**:
           - Start with `function.expand` to gather necessary context. Specify what needs expansion using `scope_expansion` or `def_expansion` parameters:
             - `scope_expansion` example: `scope_expansion: [{file: "src/utils.js", range: (10, 50)}]` where `file` is the file needing context expansion and `range` specifies the line numbers for the scope.
             - `def_expansion` example: `def_expansion: [{file: "src/utils.js", name: "calculateInterest", line: 15}]` where you define the file path, the function or definition name, and the line number to expand upon.
           - After expanding the code with `function.expand`, there should always be a follow-up analysis or action, not an immediate call to `function.none`.
        
        3. **Applying `function.range`**:
           - Use `function.range` after expanding the code to identify relevant sections within the expanded context. Provide descriptions or keywords related to the issue to guide the range identification.
        
        4. **Finalizing with `function.none`**:
           - Use `function.none` after `function.range` when all necessary code sections and their ranges are identified, and no further expansion or range identification is required.
        
        This enhanced prompt ensures that the process of using `function.expand`, `function.range`, and `function.none` is clear and structured, including how to properly provide parameters for expansions, ensuring a thorough and effective analysis and modification of the code.
        
        "#);
    s
}

pub fn file_explanation(question: &str, path: &str, code: &str) -> String {
    format!(
        r#"Below are some lines from the file /{path}. Each line is numbered.

#####

{code}

#####

Your job is to perform the following tasks:
1. Find all the relevant line ranges of code.
2. DO NOT cite line ranges that you are not given above
3. You MUST answer with only line ranges. DO NOT answer the question

Q: find Kafka auth keys
A: [[12,15]]

Q: find where we submit payment requests
A: [[37,50]]

Q: auth code expiration
A: [[486,501],[520,560],[590,631]]

Q: library matrix multiplication
A: [[68,74],[82,85],[103,107],[187,193]]

Q: how combine result streams
A: []

Q: {question}
A: "#
    )
}
