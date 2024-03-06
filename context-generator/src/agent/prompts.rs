
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

pub fn answer_article_prompt(aliases: &[usize], context: &str) -> String {
    // Return different prompts depending on whether there is one or many aliases
    let one_prompt = format!(
        r#"{context}#####

A user is looking at the code above, your job is to write an article answering their query.

Your output will be interpreted as bloop-markdown which renders with the following rules:
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

pub fn hypothetical_document_prompt_v2(query: &str, language: &str, symbol_name: &str, symbol_type: &str) -> String {
    format!(
        r#"Write a code snippet in {language} language that could hypothetically be returned by a code search engine as the answer to the query: {query}

- Write the snippets in {language} language that is likely given the query
- Use a {symbol_type} named {symbol_name} while creating the snippet in language {language}
- Use the {symbol_name} more than one time in the snippet
- The snippet should be between 5 and 10 lines long
- Surround the snippet in triple backticks


For example:

Query: What's the Qdrant threshold?
language: Rust
symbol_type: function
symbol_name: SearchPoints

```rust
pub fn search_points(&self, query: &Query, filter: Option<&Filter>, top: usize) -> Result<Vec<ScoredPoint>> {{
    let mut request = SearchPoints::new(query, top);
    if let Some(filter) = filter {{
        request = request.with_filter(filter);
    }}
    let response = self.client.search_points(request).await?;
    Ok(response.points)
}}

```"#
    )
}

pub fn hypothetical_document_prompt(query: &str) -> String {
    format!(
        r#"Write a code snippet that could hypothetically be returned by a code search engine as the answer to the query: {query}

- Write the snippets in a programming or markup language that is likely given the query
- The snippet should be between 5 and 10 lines long
- Surround the snippet in triple backticks

For example:

What's the Qdrant threshold?

```rust
SearchPoints {{
    limit,
    vector: vectors.get(idx).unwrap().clone(),
    collection_name: COLLECTION_NAME.to_string(),
    offset: Some(offset),
    score_threshold: Some(0.3),
    with_payload: Some(WithPayloadSelector {{
        selector_options: Some(with_payload_selector::SelectorOptions::Enable(true)),
    }}),
```"#
    )
}


pub fn hypothetical_document_prompt_v3(query: &str, symbols: Vec<(String, String, String)>) -> String {
    let lang = symbols[0].clone().0;
    let symbol_type_0 = symbols[0].clone().1;
    let symbol_name_0 = symbols[0].clone().2;
    let symbol_type_1 = symbols[1].clone().1;
    let symbol_name_1 = symbols[1].clone().2;
    let symbol_type_2 = symbols[2].clone().1;
    let symbol_name_2 = symbols[2].clone().2;

    format!(
        r#"Write a code snippet in {lang} language that could hypothetically be returned by a code search engine as the answer to the query: {query}

- Write the snippets in {lang} language that is likely given the query
- Use a {symbol_name_0} named {symbol_type_0} while creating the snippet in language {lang}
- Use a {symbol_name_1} named {symbol_type_1} while creating the snippet in language {lang}
- Use a {symbol_name_2} named {symbol_type_2} while creating the snippet in language {lang}
- The snippet should be between 5 and 10 lines long
- Surround the snippet in triple backticks


For example:

Query: What's the Qdrant threshold?
language: Rust
symbol_type: function
symbol_name: search_points

symbol_type: variable 
symbol_name: request

symbol_type: module 
symbol_name: SearchPoints

```rust
use crate::SearchPoints;

pub fn search_points(&self, query: &Query, filter: Option<&Filter>, top: usize) -> Result<Vec<ScoredPoint>> {{
    let mut request = SearchPoints::new(query, top);
    if let Some(filter) = filter {{
        request = request.with_filter(filter);
    }}
    let response = self.client.search_points(request).await?;
    Ok(response.points)
}}

```"#
    )
}
pub fn try_parse_hypothetical_documents(document: &str) -> Vec<String> {
    let pattern = r"```([\s\S]*?)```";
    let re = regex::Regex::new(pattern).unwrap();

    re.captures_iter(document)
        .map(|m| m[1].trim().to_string())
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_hypothetical_document() {
        let document = r#"Here is some pointless text

        ```rust
pub fn final_explanation_prompt(context: &str, query: &str, query_history: &str) -> String {
    struct Rule<'a> {
        title: &'a str,
        description: &'a str,
        note: &'a str,
        schema: &'a str,```

Here is some more pointless text

```
pub fn functions() -> serde_json::Value {
    serde_json::json!(
```"#;
        let expected = vec![
            r#"rust
pub fn final_explanation_prompt(context: &str, query: &str, query_history: &str) -> String {
    struct Rule<'a> {
        title: &'a str,
        description: &'a str,
        note: &'a str,
        schema: &'a str,"#,
            r#"pub fn functions() -> serde_json::Value {
    serde_json::json!("#,
        ];

        assert_eq!(try_parse_hypothetical_documents(document), expected);
    }
}
