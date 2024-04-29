use anyhow::Result;
use ndarray::Axis;
use ort::{CPUExecutionProvider, GraphOptimizationLevel, Session};
use tokenizers::Tokenizer;

pub type Embedding = Vec<f32>;

// create a struct for onnx and tokenizer container
pub struct TokenizerOnnx {
    pub tokenizer: Tokenizer,
    pub session: ort::Session,
}

impl TokenizerOnnx {
    pub fn new(model_path: &str) -> Result<Self> {
        let tokenizer = get_tokenizer(model_path)?;
        let session = get_ort_session(model_path)?;
        Ok(Self { tokenizer, session })
    }

    pub fn get_embedding(&self, sequence: &str) -> anyhow::Result<Embedding> {
        let tokenizer_output = self.tokenizer.encode(sequence, true).unwrap();

        let input_ids = tokenizer_output.get_ids();
        let attention_mask = tokenizer_output.get_attention_mask();
        let token_type_ids = tokenizer_output.get_type_ids();
        let length = input_ids.len();

        let inputs_ids_array = ndarray::Array::from_shape_vec(
            (1, length),
            input_ids.iter().map(|&x| x as i64).collect(),
        )?;

        let attention_mask_array = ndarray::Array::from_shape_vec(
            (1, length),
            attention_mask.iter().map(|&x| x as i64).collect(),
        )?;

        let token_type_ids_array = ndarray::Array::from_shape_vec(
            (1, length),
            token_type_ids.iter().map(|&x| x as i64).collect(),
        )?;

        //let array = ndarray::Array::from_shape_vec((1,), vec![document]).unwrap();

        let outputs = self.session.run(ort::inputs![
            ort::Value::from_array(inputs_ids_array.into_dyn())?,
            ort::Value::from_array(attention_mask_array.into_dyn())?,
            ort::Value::from_array(token_type_ids_array.into_dyn())?,
        ]?)?;

        let output_tensor = outputs[0].try_extract_tensor()?;
        let sequence_embedding = output_tensor.view();
        let pooled = sequence_embedding.mean_axis(Axis(1)).unwrap();
        Ok(pooled.to_owned().as_slice().unwrap().to_vec())
    }
}

pub fn get_tokenizer(model_path: &str) -> Result<Tokenizer> {
    // create pathbuf from the tokenizer_path
    // get current directory of the package and join model/tokenizer.json file path
    let tokenizer_path = std::path::PathBuf::from(model_path)
        .join("tokenizer.json")
        .to_string_lossy()
        .to_string();

    let tokenizer = tokenizers::Tokenizer::from_file(tokenizer_path).map_err(|e| {
        let error_message = e.to_string(); // Extract the error message
        log::error!("Error creating tokenizer: {}", error_message); // log the error
        anyhow::Error::msg(error_message) // Create an anyhow::Error with the message
    })?;
    Ok(tokenizer)
}

pub fn get_ort_session(model_path: &str) -> Result<ort::Session> {
    let onnx_model_path = std::path::PathBuf::from(model_path)
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
