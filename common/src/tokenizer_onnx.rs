
use anyhow::Result;
use ort::{CPUExecutionProvider, GraphOptimizationLevel, Session};
use tokenizers::Tokenizer;

pub fn get_tokenizer() -> Result<Tokenizer> {
    // get current directory of the package and join model/tokenizer.json file path
    let tokenizer_path = std::env::current_dir()?
    .join("model")
    .join("tokenizer.json")
    .to_string_lossy()
    .to_string();

    let tokenizer = tokenizers::Tokenizer::from_file(tokenizer_path).map_err(|e| {
        let error_message = e.to_string(); // Extract the error message
        log::error!("Error creating tokenizer: {}", error_message); // Optional: log the error
        anyhow::Error::msg(error_message) // Create an anyhow::Error with the message
    })?;
    Ok(tokenizer)
}

pub fn get_ort_session() -> Result<ort::Session> {
    let onnx_model_path = std::env::current_dir()?
    .join("model")
    .join("model.onnx")
    .to_string_lossy()
    .to_string();

    let session = Session::builder()?
    .with_execution_providers([CPUExecutionProvider::default().build()])?
    .with_optimization_level(GraphOptimizationLevel::Level3)?
    .with_intra_threads(4)?
    .commit_from_file(onnx_model_path)
    .map_err(anyhow::Error::from)?;

    Ok(session)
}