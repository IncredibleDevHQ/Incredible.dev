use tokio::fs::File;
use common::CodeUnderstanding;
use tokio::io::AsyncReadExt;
use std::path::Path;
use common::TaskList;


// Define an asynchronous function to read and deserialize the JSON data.
pub async fn read_code_understanding_from_file<P: AsRef<Path>>(path: P) -> std::io::Result<CodeUnderstanding> {
    let mut file = File::open(path).await?;
    let mut data = String::new();
    file.read_to_string(&mut data).await?;
    let code_understanding: CodeUnderstanding = serde_json::from_str(&data)?;
    Ok(code_understanding)
}

pub async fn read_task_list_from_file<P: AsRef<Path>>(path: P) -> std::io::Result<TaskList> {
    let mut file = File::open(path).await?;
    let mut data = String::new();
    file.read_to_string(&mut data).await?;
    let task_list: TaskList = serde_json::from_str(&data)?;
    Ok(task_list)
}
