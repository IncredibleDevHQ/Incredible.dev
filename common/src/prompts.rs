use log::debug;

use crate::models::{
    CodeChunk, CodeSpanRequest, TaskDetailsWithContext, TasksQuestionsAnswersDetails,
};

pub fn functions(add_proc: bool) -> serde_json::Value {
    let mut funcs = serde_json::json!(
        [
            {
                "name": "code",
                "description":  "Search the contents of files in a codebase semantically. Results will not necessarily match search terms exactly, but should be related.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The query with which to search. This should consist of keywords that might match something in the codebase, e.g. 'react functional components', 'contextmanager', 'bearer token'. It should NOT contain redundant words like 'usage' or 'example'."
                        }
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "path",
                "description": "Search the pathnames in a codebase. Use when you want to find a specific file or directory. Results may not be exact matches, but will be similar by some edit-distance.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The query with which path to search. This should consist of keywords that might match a path, e.g. 'server/src'."
                        }
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "none",
                "description": "Call this to answer the user. Call this only when you have enough information to answer the user's query.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "paths": {
                            "type": "array",
                            "items": {
                                "type": "integer",
                                "description": "The indices of the paths to answer with respect to. Can be empty if the answer is not related to a specific path."
                            }
                        }
                    },
                    "required": ["paths"]
                }
            },
        ]
    );

    if add_proc {
        funcs.as_array_mut().unwrap().push(
            serde_json::json!(
            {
                "name": "proc",
                "description": "Read one or more files and extract the line ranges that are relevant to the search terms",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The query with which to search the files."
                        },
                        "paths": {
                            "type": "array",
                            "items": {
                                "type": "integer",
                                "description": "The indices of the paths to search. paths.len() <= 5"
                            }
                        }
                    },
                    "required": ["query", "paths"]
                }
            }
            )
        );
    }
    funcs
}

pub fn system<'a>(paths: impl IntoIterator<Item = &'a str>) -> String {
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
        r#"Your job is to choose the best action. Call functions to find information that will help answer the user's query. Call functions.none when you have enough information to answer. Follow these rules at all times:

- ALWAYS call a function, DO NOT answer the question directly, even if the query is not in English
- DO NOT call a function that you've used before with the same arguments
- DO NOT assume the structure of the codebase, or the existence of files or folders
- Call functions.none with paths that you are confident will help answer the user's query
- In most cases call functions.code or functions.path functions before calling functions.none
- If the user is referring to, or asking for, information that is in your history, call functions.none
- If after attempting to gather information you are still unsure how to answer the query, call functions.none
- If the query is a greeting, or not a question or an instruction call functions.none
- When calling functions.code or functions.path, your query should consist of keywords. E.g. if the user says 'What does contextmanager do?', your query should be 'contextmanager'. If the user says 'How is contextmanager used in app', your query should be 'contextmanager app'. If the user says 'What is in the src directory', your query should be 'src'
- If functions.code or functions.path did not return any relevant information, call them again with a SIGNIFICANTLY different query. The terms in the new query should not overlap with terms in your old one
- If the output of a function is empty, try calling the function again with DIFFERENT arguments OR try calling a different function
- Only call functions.proc with path indices that are under the PATHS heading above.
- Call functions.proc with paths that might contain relevant information. Either because of the path name, or to expand on code that's already been returned by functions.code. Rank these paths based on their relevancy, and pick only the top five paths, and reject others
- DO NOT call functions.proc with more than 5 paths, it should 5 or less paths
- DO NOT call functions.proc on the same file more than once
- ALWAYS call a function. DO NOT answer the question directly"#);
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

pub fn answer_article_prompt(aliases: &[usize], context: &str) -> String {
    // Return different prompts depending on whether there is one or many aliases
    let one_prompt = format!(
        r#"{context}#####

A user is looking at the code above, your job is to write an article answering their query.

Your output will be interpreted as Incredible-markdown which renders with the following rules:
- Inline code must be expressed as a link to the correct line of code using the URL format: `[bar](src/foo.rs#L50)` or `[bar](src/foo.rs#L50-L54)`
- Do NOT output bare symbols. ALL symbols must include a link
  - E.g. Do not simply write `Bar`, write [`Bar`](src/bar.rs#L100-L105).
  - E.g. Do not simply write "Foos are functions that create `Foo` values out of thin air." Instead, write: "Foos are functions that create [`Foo`](src/foo.rs#L80-L120) values out of thin air."
- Only internal links to the current file work
- Basic markdown text formatting rules are allowed, and you should use titles to improve readability

Here is an example response:

A function [`openCanOfBeans`](src/beans/open.py#L7-L19) is defined. This function is used to handle the opening of beans. It includes the variable [`openCanOfBeans`](src/beans/open.py#L9) which is used to store the value of the tin opener.
"#
    );

    let many_prompt = format!(
        r#"{context}Your job is to answer a query about a codebase using the information above.

Provide only as much information and code as is necessary to answer the query, but be concise. Keep number of quoted lines to a minimum when possible. If you do not have enough information needed to answer the query, do not make up an answer.
When referring to code, you must provide an example in a code block.

Respect these rules at all times:
- Do not refer to paths by alias, expand to the full path
- Link ALL paths AND code symbols (functions, methods, fields, classes, structs, types, variables, values, definitions, directories, etc) by embedding them in a markdown link, with the URL corresponding to the full path, and the anchor following the form `LX` or `LX-LY`, where X represents the starting line number, and Y represents the ending line number, if the reference is more than one line.
  - For example, to refer to lines 50 to 78 in a sentence, respond with something like: The compiler is initialized in [`src/foo.rs`](src/foo.rs#L50-L78)
  - For example, to refer to the `new` function on a struct, respond with something like: The [`new`](src/bar.rs#L26-53) function initializes the struct
  - For example, to refer to the `foo` field on a struct and link a single line, respond with something like: The [`foo`](src/foo.rs#L138) field contains foos. Do not respond with something like [`foo`](src/foo.rs#L138-L138)
  - For example, to refer to a folder `foo`, respond with something like: The files can be found in [`foo`](path/to/foo/) folder
- Do not print out line numbers directly, only in a link
- Do not refer to more lines than necessary when creating a line range, be precise
- Do NOT output bare symbols. ALL symbols must include a link
  - E.g. Do not simply write `Bar`, write [`Bar`](src/bar.rs#L100-L105).
  - E.g. Do not simply write "Foos are functions that create `Foo` values out of thin air." Instead, write: "Foos are functions that create [`Foo`](src/foo.rs#L80-L120) values out of thin air."
- Link all fields
  - E.g. Do not simply write: "It has one main field: `foo`." Instead, write: "It has one main field: [`foo`](src/foo.rs#L193)."
- Link all symbols, even when there are multiple in one sentence
  - E.g. Do not simply write: "Bars are [`Foo`]( that return a list filled with `Bar` variants." Instead, write: "Bars are functions that return a list filled with [`Bar`](src/bar.rs#L38-L57) variants."
- Always begin your answer with an appropriate title
- Always finish your answer with a summary in a [^summary] footnote
  - If you do not have enough information needed to answer the query, do not make up an answer. Instead respond only with a [^summary] f
ootnote that asks the user for more information, e.g. `assistant: [^summary]: I'm sorry, I couldn't find what you were looking for, could you provide more information?`
- Code blocks MUST be displayed to the user using XML in the following formats:
  - Do NOT output plain markdown blocks, the user CANNOT see them
  - To create new code, you MUST mimic the following structure (example given):
###
The following demonstrates logging in JavaScript:
<GeneratedCode>
<Code>
console.log("hello world")
</Code>
<Language>JavaScript</Language>
</GeneratedCode>
###
  - To quote existing code, use the following structure (example given):
###
This is referred to in the Rust code:
<QuotedCode>
<Code>
println!("hello world!");
println!("hello world!");
</Code>
<Language>Rust</Language>
<Path>src/main.rs</Path>
<StartLine>4</StartLine>
<EndLine>5</EndLine>
</QuotedCode>
###
  - `<GeneratedCode>` and `<QuotedCode>` elements MUST contain a `<Language>` value, and `<QuotedCode>` MUST additionally contain `<Path>`, `<StartLine>`, and `<EndLine>`.
  - Note: the line range is inclusive
- When writing example code blocks, use `<GeneratedCode>`, and when quoting existing code, use `<QuotedCode>`.
- You MUST use XML code blocks instead of markdown."#
    );

    if aliases.len() == 1 {
        one_prompt
    } else {
        many_prompt
    }
}

pub fn answer_article_prompt_new(aliases: &[usize], context: &str, objective: &str) -> String {
    // Return different prompts depending on whether there is one or many aliases
    let json_example = r#"
    {
        "answer": "Actual answer",
        "used_context": [
            {
                "file": {
                    "path": "src/bar.rs",
                    "highlights": [
                        "Handles the configuration loading",
                        "Initializes the application state"
                    ],
                    "answer_part": [
                        "Explanation of how the config is loaded as referenced in the answer",
                        "Details on state initialization"
                    ]
                },
                "range": {
                    "start": 15,
                    "end": 20
                }
            },
            {
                "file": {
                    "path": "src/foo.rs",
                    "highlights": [
                        "Performs authentication checks",
                        "Routes are declared here"
                    ],
                    "answer_part": [
                        "Authentication process details",
                        "Route declaration specifics"
                    ]
                },
                "range": {
                    "start": 42,
                    "end": 42
                }
            },
            {
                "file": {
                    "path": "src/utils.rs",
                    "highlights": [
                        "Utility functions for data formatting"
                    ],
                    "answer_part": [
                        "Usage of utility functions to format data"
                    ]
                },
                "range": {
                    "start": 58,
                    "end": 58
                }
            }
        ],
        "clarifying_questions": [
            "Is there a specific coding standard or style guide you follow for naming variables and methods?",
            "Can you clarify the expected behavior of the system when an error occurs?",
            "Is there a fallback or error handling mechanism in place that should be considered?"
        ]
    }
    "#;

    let example_context = r#"
    {
        "file": {
            "path": "src/bar.rs",
            "highlights": [
                "Handles the configuration loading",
                "Initializes the application state"
            ],
            "answer_part": [
                "Explanation of how the config is loaded as referenced in the answer",
                "Details on state initialization"
            ]
        },
        "range": {
            "start": 15,
            "end": 20
        }
    }
    "#;

    let example_clarifying_questions = r#"
    {
        "clarifying_questions": [
            "Is there a specific coding standard or style guide you follow for naming variables and methods?",
            "Can you clarify the expected behavior of the system when an error occurs?",
            "Is there a fallback or error handling mechanism in place that should be considered?"
        ]
    }
    "#;

    let var_name = format!(
        r#"Think like a senior software developer with exceptional empathy and communication skills for junior software engineers they work with. Look at the code above, using the code your job is to give critical and necessary information as answer, and generate the used_context and clarifying_questions inorder for a junior software engineer to solve the task below.  
        ##TASK##
        
        {objective}
        
        Produce the result in the following strict JSON format:
        ##### JSON Output Example:
        - Ensure that the response adheres to valid JSON formatting as outlined. Never violate these rules when generating entries for the JSON.
        {json_example}

In the above json response structure, "answer" field should contain the actual answer to the question. The "used_context" field should contain the necessary context from the codebase to support the answer. The "clarifying_questions" field should contain any questions that would help clarify the requirements or the codebase.

Respect these rules all the time for generating "answer" field in the JSON:

Your "answer" output will be interpreted as Incredible-markdown which renders with the following rules:
- Inline code must be expressed as a link to the correct line of code using the URL format: `[bar](src/foo.rs#L50)` or `[bar](src/foo.rs#L50-L54)`
- Do NOT output bare symbols. ALL symbols must include a link
  - E.g. Do not simply write `Bar`, write [`Bar`](src/bar.rs#L100-L105).
  - E.g. Do not simply write "Foos are functions that create `Foo` values out of thin air." Instead, write: "Foos are functions that create [`Foo`](src/foo.rs#L80-L120) values out of thin air."
- Only internal links to the current file work
- Basic markdown text formatting rules are allowed, and you should use titles to improve readability

Here is an example for the "answer" field in the JSON output:

A function [`openCanOfBeans`](src/beans/open.py#L7-L19) is defined. This function is used to handle the opening of beans. It includes the variable [`openCanOfBeans`](src/beans/open.py#L9) which is used to store the value of the tin opener.

Respect these rules at all times for "used_context" generation in the JSON:
- For `used_context` generation:
  - Only include entries in `used_context` that are directly used in your answer. If the file is not referenced in the answer and does not provide necessary context directly impacting the understanding of the answer, do not include it in `used_context` or `answer_part`.
  - `file`:
    - Include the `path` for each file that provides context for your answer.
  - `highlights`: 
    - This should be an array that lists key functionalities or concepts shown in the code at the specified path. These highlights must directly relate to the content of the answer.
  - `answer_part`: 
    - This should be an array containing specific segments of your answer that refer to or rely on the information from the file. This should be directly quotes from the answer. If the file is not directly referenced, it should not be included.
  - `range`: 
    - Specify the exact lines of code being referenced with a `start`. Include an `end` only if more than one consecutive line is discussed.
    - If only a single line is crucial for the answer, specify only the `start`.
- Ensure that every piece of code, functionality, or concept linked in `used_context` has a clear purpose and connection to the main answer. Any code or details that do not support the answer directly should not be included.

Here is the example for the "used_context" field in the JSON output:

{example_context}

Respect these rules all the time for generating "clarifying_questions" in the JSON:
  - List critical clarifying questions that arise while coding to solve the tasks described. Questions should target areas where information is conflicting, ambiguous, or missing.
  - Each question should be phrased in a way that prompts a direct and actionable response, which could help continue the coding process effectively.
  - Focus on identifying gaps in the code, documentation, or requirements that could block progress or lead to misunderstandings.
  - Questions should be specific and directly related to the tasks at hand, aiming to clarify the exact nature of the problem or the information required.
Here is the example for the "clarifying_questions" field in the JSON output:

{example_clarifying_questions}

Respect these JSON formatting rules for the generated output:
Strictly adhere to the JSON format when constructing the output. This includes:
- Using double quotes for strings.
- Ensuring proper use of commas between items in arrays and objects.
- Confirming that all brackets and braces are correctly paired and closed.
- Avoiding trailing commas after the last element in arrays or objects.

"#
    );
    let one_prompt = var_name;

    let many_prompt = format!(
        r#"Think like a senior software developer with exceptional empathy and communication skills for junior software engineers they work with. Look at the code above, using the code your job is to give critical and necessary information as answer, and generate the used_context and clarifying_questions inorder for a junior software engineer to solve the task below.  
        Use should only use the information from the code above to answer the query, and generate the output.
        ##TASK##
        
        {objective}
        
        Produce the result in the following strict JSON format:
        ##### JSON Output Example:
        - Ensure that the response adheres to valid JSON formatting as outlined. Never violate these rules when generating entries for the JSON.
        {json_example}
        
        In the above json response structure,  "answer" field should contain the actual answer to the question. The "used_context" field should contain the necessary context from the codebase to support the answer. The "clarifying_questions" field should contain any questions that would help clarify the requirements or the codebase.
        
        Respect these rules all the time for generating "answer" field in the JSON:
- Do not refer to paths by alias, expand to the full path
- Link ALL paths AND code symbols (functions, methods, fields, classes, structs, types, variables, values, definitions, directories, etc) by embedding them in a markdown link, with the URL corresponding to the full path, and the anchor following the form `LX` or `LX-LY`, where X represents the starting line number, and Y represents the ending line number, if the reference is more than one line.
  - For example, to refer to lines 50 to 78 in a sentence, respond with something like: The compiler is initialized in [`src/foo.rs`](src/foo.rs#L50-L78)
  - For example, to refer to the `new` function on a struct, respond with something like: The [`new`](src/bar.rs#L26-53) function initializes the struct
  - For example, to refer to the `foo` field on a struct and link a single line, respond with something like: The [`foo`](src/foo.rs#L138) field contains foos. Do not respond with something like [`foo`](src/foo.rs#L138-L138)
  - For example, to refer to a folder `foo`, respond with something like: The files can be found in [`foo`](path/to/foo/) folder
- Do not print out line numbers directly, only in a link
- Do not refer to more lines than necessary when creating a line range, be precise
- Do NOT output bare symbols. ALL symbols must include a link
  - E.g. Do not simply write `Bar`, write [`Bar`](src/bar.rs#L100-L105).
  - E.g. Do not simply write "Foos are functions that create `Foo` values out of thin air." Instead, write: "Foos are functions that create [`Foo`](src/foo.rs#L80-L120) values out of thin air."
- Link all fields
  - E.g. Do not simply write: "It has one main field: `foo`." Instead, write: "It has one main field: [`foo`](src/foo.rs#L193)."
- Link all symbols, even when there are multiple in one sentence
  - E.g. Do not simply write: "Bars are [`Foo`]( that return a list filled with `Bar` variants." Instead, write: "Bars are functions that return a list filled with [`Bar`](src/bar.rs#L38-L57) variants."
- Always begin your answer with an appropriate title
- Always finish your answer with a summary in a [^summary] footnote
  - If you do not have enough information needed to answer the query, do not make up an answer. Instead respond only with a [^summary] f
ootnote that asks the user for more information, e.g. `assistant: [^summary]: I'm sorry, I couldn't find what you were looking for, could you provide more information?`
- Code blocks MUST be displayed to the user using XML in the following formats:
  - Do NOT output plain markdown blocks, the user CANNOT see them
  - To create new code, you MUST mimic the following structure (example given):
###
The following demonstrates logging in JavaScript:
<GeneratedCode>
<Code>
console.log("hello world")
</Code>
<Language>JavaScript</Language>
</GeneratedCode>
###
  - To quote existing code, use the following structure (example given):
###
This is referred to in the Rust code:
<QuotedCode>
<Code>
println!("hello world!");
println!("hello world!");
</Code>
<Language>Rust</Language>
<Path>src/main.rs</Path>
<StartLine>4</StartLine>
<EndLine>5</EndLine>
</QuotedCode>
###
  - `<GeneratedCode>` and `<QuotedCode>` elements MUST contain a `<Language>` value, and `<QuotedCode>` MUST additionally contain `<Path>`, `<StartLine>`, and `<EndLine>`.
  - Note: the line range is inclusive
- When writing example code blocks, use `<GeneratedCode>`, and when quoting existing code, use `<QuotedCode>`.
- You MUST use XML code blocks instead of markdown.
Here is an example for the "answer" field in the JSON output:

A function [`openCanOfBeans`](src/beans/open.py#L7-L19) is defined. This function is used to handle the opening of beans. It includes the variable [`openCanOfBeans`](src/beans/open.py#L9) which is used to store the value of the tin opener.

Respect these rules at all times for "used_context" generation in the JSON:
- For `used_context` generation:
  - Only include entries in `used_context` that are directly used in your answer. If the file is not referenced in the answer and does not provide necessary context directly impacting the understanding of the answer, do not include it in `used_context` or `answer_part`.
  - `file`:
    - Include the `path` for each file that provides context for your answer.
  - `highlights`: 
    - This should be an array that lists key functionalities or concepts shown in the code at the specified path. These highlights must directly relate to the content of the answer.
  - `answer_part`: 
    - This should be an array containing specific segments of your answer that refer to or rely on the information from the file. This should be directly quotes from the answer. If the file is not directly referenced, it should not be included.
  - `range`: 
    - Specify the exact lines of code being referenced with a `start`. Include an `end` only if more than one consecutive line is discussed.
    - If only a single line is crucial for the answer, specify only the `start`.
- Ensure that every piece of code, functionality, or concept linked in `used_context` has a clear purpose and connection to the main answer. Any code or details that do not support the answer directly should not be included.

Here is the example for the "used_context" field in the JSON output:

{example_context}

Respect these rules all the time for generating "clarifying_questions" in the JSON:
  - List critical clarifying questions that arise while coding to solve the tasks described. Questions should target areas where information is conflicting, ambiguous, or missing.
  - Each question should be phrased in a way that prompts a direct and actionable response, which could help continue the coding process effectively.
  - Focus on identifying gaps in the code, documentation, or requirements that could block progress or lead to misunderstandings.
  - Questions should be specific and directly related to the tasks at hand, aiming to clarify the exact nature of the problem or the information required.

Respect these JSON formatting rules for the generated output:
Strictly adhere to the JSON format when constructing the output. This includes:
- Using double quotes for strings.
- Ensuring proper use of commas between items in arrays and objects.
- Confirming that all brackets and braces are correctly paired and closed.
- Avoiding trailing commas after the last element in arrays or objects.
  "#

    );

    if aliases.len() == 1 {
        debug!("One alias");
        one_prompt
    } else {
        debug!("Many aliases");
        many_prompt
    }
}

pub fn question_concept_generator_prompt(issue_desc: &str, repo_name: &str) -> String {
    let question_concept_generator_prompt = format!(
        r#"#####

        
        You are a Tool that takes an issue description for a developer task and deconstructs it into actionable tasks and subtasks focusing on code modifications. Alongside each task and subtask, you will generate questions aimed at understanding the current codebase. These questions should be specific and insightful, focusing on the existing codebase's structure and behavior without directly addressing the specific changes to be made.

        Emphasize the need for specificity in your questions. Avoid using vague references like 'this endpoint' or 'that endpoint.' Instead, require the questions to specify exact endpoints, functionalities, or components. For instance, instead of asking 'How does this endpoint respond?', ask 'How does the /retrieve endpoint respond, and what is its data structure?'.

        Before generating tasks and subtasks, introspect whether a junior developer would have enough information to understand what problem or issue needs to be solved based on the provided issue description. The clarity and specificity of the issue description are crucial for creating actionable and understandable tasks.

        - Generate 1 to 5 main tasks based on the issue description, ensuring each task is detailed, clear, and actionable. Avoid vagueness to enable a junior engineer to proceed with the tasks without the need for further guidance. For example, instead of creating a task like 'Improve the API,' specify what improvements are needed by stating, 'Update the GET endpoint in the API to handle error status codes more effectively.'

        - If the issue description is vague or lacks specific details, making it challenging for a junior developer to grasp the required actions, do not generate tasks. Instead, populate the 'ask_user' field to request more detailed information that would clarify the task requirements. Remember, if 'ask_user' is populated, the 'tasks' array must remain empty to avoid presenting conflicting instructions.

        ----Examples of vague issue descriptions from a junior developer's perspective----

        Example 1:
        issue description- "Improve the coordinator service API."
        repo_name- "service-improvement-project"

        To a junior developer, this is vague because it doesn't specify what 'improve' means. Does it refer to performance tuning, adding new features, or fixing existing bugs? Without this information, they wouldn't know where to begin.

        Response from LLM:
        {{
            "tasks": [],
            "ask_user": "Can you provide more specific details on how you would like to improve the coordinator service API? Are there specific performance issues, additional features needed, or bugs that need to be addressed?"
        }}

        Example 2:
        issue description- "Debug the API."
        repo_name- "api-debugging-project"

        This lacks detail on what the debugging entails. Are there known issues to address, or is the task to find potential unknown problems? A junior developer would need more context to approach this task effectively.

        Response from LLM:
        {{
            "tasks": [],
            "ask_user": "Could you specify what aspects of the API should be debugged? Are we looking for known issues, performance optimizations, or general stability checks? Any particular endpoints or functionalities that require attention?"
        }}

        Example 3:
        issue description- "Check the API for errors."
        repo_name- "api-error-checking-project"

        This description is too general and doesn't provide enough context. What type of errors are to be checked? Are there any recent changes or areas where errors are suspected?

        Response from LLM:
        {{
            "tasks": [],
            "ask_user": "Please clarify what type of errors we should focus on in the API. Are there specific modules, endpoints, or recent updates we should concentrate on? Should we also look into error logging or monitoring systems for any unusual activity?"
        }}

        ----Example for a well-defined issue description----

        issue description- "Enhance the Service A API to integrate with the Data Processing API for improved efficiency."
        repo_name- "service-communication-enhancement"

        Response from LLM:
        {{
          "tasks": [
            {{
              "task": "Enhance the Service A API to integrate with the Data Processing API for improved efficiency",
              "subtasks": [
                {{
                  "subtask": "Analyze the current interaction between Service A API and the Data Processing API",
                  "questions": [
                    "How does Service A API currently interact with the Data Processing API? I'm trying to Analyze the current interaction between Service A API and the Data Processing API, so that I can solve how to Enhance the Service A API to integrate with the Data Processing API for improved efficiency.",
                    "What data structures are used in the communication between Service A API and the Data Processing API? I'm trying to Analyze the current interaction between Service A API and the Data Processing API, so that I can Enhance the Service A API to integrate with the Data Processing API for improved efficiency "
                  ]
                }}
              ]
            }}
          ],
          "ask_user": ""
        }}

        Your job is to perform the following tasks:
        - Generate 1 to 5 main tasks based on the issue description, ensuring each task is detailed, clear, and actionable. Avoid creating vague tasks like 'Improve the API,' which do not provide enough information for a junior engineer to act upon. Instead, detail what specific improvements are needed, as in 'Update the GET endpoint in the API to handle error status codes more effectively.'
        - For each main task, define 1 to 5 subtasks that provide specific steps and actions required.
        - For each subtask, create 1 to 4 questions that delve into the codebase's existing structure and behavior, relevant to the task at hand. Ensure that the questions are specific and refer to exact components or endpoints.
        - Append a concise version of the subtask and the task for each question so that the questions has its context. Let's say of the task is "Update the GET endpoint in the API to handle error status codes more effectively", then the subtask could be "Analyze the current error handling mechanism in the GET endpoint" and the question could be "How does the current error handling mechanism in the GET endpoint work? I'm trying to analyze the current error handling mechanism in the GET endpoint so that I can update the GET endpoint in the API to handle error status codes more effectively."

        When referring to APIs or other components, always use specific and descriptive names. Never use generic terms like "other API." Instead, clarify the API's purpose or function, describing it in a way that reflects its role in the system.

        RETURN a JSON object containing the structured breakdown of tasks, subtasks, and an 'ask_user' field for further clarifications if necessary. The 'ask_user' field should only be populated if more information is needed, and in such cases, the 'tasks' array should remain empty. This ensures clarity and prevents any confusion about the tool's requests for additional information.

        Ensure that the tasks and subtasks explicitly outline the modification actions required. The questions should aid in providing a deep understanding of the current codebase, focusing on its existing structures and behaviors, without suggesting direct actions.

        IMPORTANT: If 'ask_user' is populated to clarify the issue, the 'tasks' array must be empty to maintain clear communication and avoid conflicting instructions. This ensures that the tool does not generate tasks based on assumptions or incomplete information. This measure is crucial in ensuring that a junior developer is not misguided by incomplete or ambiguous tasks which could lead to confusion or ineffective problem-solving.

        issue description- '''{issue_desc}'''
        repo_name- '''{repo_name}'''

        DO NOT confuse tasks with questions. Tasks should clearly outline 'what' needs to be done, providing enough detail for a junior engineer to understand and execute the tasks without further clarifications. The 'ask_user' prompt is vital for obtaining the necessary clarity and should be used whenever the issue description lacks the specificity needed for task generation.

        Always ensure that the tasks generated are actionable, clear, and provide sufficient context and detail for a junior developer to effectively address the issue without requiring additional information or guidance.

        Ignore the word "Response from LLM:" in the output, it is only used to give instruction, and return a valid json response.  
"#
    );

    question_concept_generator_prompt
}

pub fn create_task_answer_summarization_prompt(
    user_query: &str,
    tasks_details: &TasksQuestionsAnswersDetails,
) -> String {
    let mut prompt = format!(
        "As a junior software engineer, you've received tasks, questions, and answers related to an issue you're working on. These were provided by your colleague. Your goal is to summarize this information, preparing yourself to discuss it for better clarity. Here's the issue you're addressing:\n\nUser Query: '{}'\n\n",
        user_query
    );

    prompt += "## Task Summary:\n";

    for (i, task) in tasks_details.tasks.iter().enumerate() {
        prompt += &format!("### Task {}: {}\n", i + 1, task.task_description);
        prompt += "Key points from the answers:\n";

        // Adding questions and answers for the task in bullet points.
        for (j, question) in task.questions.iter().enumerate() {
            prompt += &format!("  - Q{}: {}\n", j + 1, question);
            if j < task.answers.len() {
                prompt += &format!("    - Answer: {}\n", task.answers[j]);
            }
        }

        // Instructions for summarizing the information.
        prompt += &format!(
            "\nPlease summarize the key information from the answers for Task {}: {}\n",
            i + 1,
            task.task_description
        );
    }

    // Section for listing critical clarifying questions.
    prompt += "\n## Critical Clarifying Questions:\n";
    prompt += "Imagine you are in the middle of coding to solve the above tasks. The following questions are crucial for continuing your coding process effectively. List any points that need further clarification, or where information seems to be conflicting, ambiguous, or missing, which could potentially block progress while coding to solve the task:\n";

    for _ in 0..20 {
        prompt += "  - Question\n";
    }

    prompt += "\nThe summary should be detailed, clear, and structured in bullet points to aid in your upcoming discussion. Group all the clarifying questions in one section at the end.\n";

    prompt
}

async fn fetch_code_snippet(
    request: CodeSpanRequest,
    code_search_url: &str,
) -> Result<Vec<CodeChunk>, anyhow::Error> {
    let client = reqwest::Client::new();
    let api_url = format!("{}/span", code_search_url);

    debug!("API URL: {}", api_url);
    // Making a POST request to the code search API with the given span request
    let response = client
        .post(api_url)
        .json(&request)
        .send()
        .await?
        .error_for_status()? // Checks for HTTP error statuses
        .json::<Vec<CodeChunk>>()
        .await?;

    Ok(response)
}

pub async fn generate_single_task_summarization_prompt(
    user_query: &str,
    url: &str,
    task_detail: &TaskDetailsWithContext,
) -> Result<String, anyhow::Error> {
    let mut prompt = format!(
        "As a junior software engineer, you're working on a task provided by your colleague. Summarize the information related to this task and prepare clarifying questions. Here's the issue you're addressing:\n\nUser Query: '{}'\n\n",
        user_query
    );

    prompt += &format!(
        "## Task Summary:\n\n### Task: {}\n",
        task_detail.task_description
    );

    // Adding code contexts to the prompt
    prompt += "#### Code Contexts:\n";
    // Inside generate_single_task_summarization_prompt function
    for context in &task_detail.merged_code_contexts {
        let code_span_request = CodeSpanRequest {
            repo: context.repo.clone(),
            branch: context.branch.clone(),
            path: context.path.clone(),
            ranges: Some(context.ranges.clone()),
            id: Some(task_detail.task_id.to_string()),
        };

        let code_snippets = fetch_code_snippet(code_span_request, url).await?;
        for snippet in code_snippets {
            //debug!("Code from the API: {}", snippet);
            prompt += &format!(
                "**File**: {}\n**Code** (Lines {} - {}):\n```\n{}\n```\n",
                snippet.path, snippet.start_line, snippet.end_line, snippet.snippet
            );
        }
    }

    prompt += "\n## Critical Clarifying Questions:\n";
    prompt += "Imagine you are in the middle of coding to solve the above tasks. The following questions are crucial for continuing your coding process effectively. List any points that need further clarification, or where information seems to be conflicting, ambiguous, or missing, which could potentially block progress while coding to solve the task:\n";

    for _ in 0..20 {
        prompt += "  - Question\n";
    }

    prompt += "\nThe summary should be detailed, clear, and structured in bullet points to aid in your upcoming discussion. Group all the clarifying questions in one section at the end.\n";

    Ok(prompt)
}
