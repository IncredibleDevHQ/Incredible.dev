use std::ops::Range;
pub mod service_interaction;



pub mod prompt_string_generator{
    use std::future::Future;
    use std::pin::Pin;

    pub trait GeneratePromptString {
        // Return a boxed future. This method will be implemented to generate a prompt.
        // The generic RequestData allows flexibility in what data is required to generate the prompt.
        fn generate_prompt(&self)  -> Pin<Box<dyn Future<Output = Result<String, Box<dyn std::error::Error>>> + Send>>;
    }
}


#[derive(serde::Serialize, serde::Deserialize, Clone, Debug, PartialEq)]
pub struct CodeContext {
    pub path: String,
    pub hidden: bool,
    pub repo: String,  // Ensure RepoRef is accessible or defined here.
    pub branch: Option<String>,
    pub ranges: Vec<Range<usize>>,
}

#[derive(serde::Serialize, serde::Deserialize, Clone, Debug, PartialEq)]
pub struct CodeUnderstanding {
    pub context: CodeContext,
    pub question: String,
    pub answer: String,
}

#[derive(serde::Serialize, serde::Deserialize, Clone, Debug, PartialEq)]
pub struct CodeUnderstandings {
    pub repo: String,
    pub issue_description: String,
    pub qna: Vec<CodeUnderstanding>,
}

// Used to get code chunks given the repo, branch, path, range and id.
#[derive(serde::Serialize, serde::Deserialize, Clone, Debug, PartialEq)]
pub struct CodeSpanRequest {
    pub repo: String,
    pub branch: Option<String>,
    pub path: String,
    // text range of the code chunk from the file to extract
    pub start: Option<usize>,
    pub end: Option<usize>,
    pub id: Option<String>,
}


