extern crate tokenizers;
use std::error::Error;
use std::ops::Range;
use std::sync::Arc;
extern crate tracing;
use anyhow::Result;
use ort::{CPUExecutionProvider, Session};
use tracing::{debug, error, info, trace, warn};
mod chunking;
mod text_range;
mod vector_payload;
use crate::ast::symbol::{SymbolKey, SymbolMetaData, SymbolValue};
use crate::config::get_model_path;
use chunking::{add_token_range, point, Chunk, DEDUCT_SPECIAL_TOKENS};
use ndarray::Axis;
use qdrant_client::prelude::{QdrantClient, QdrantClientConfig};
use qdrant_client::qdrant::{PointId, PointStruct};
use std::collections::HashMap;
use std::fmt;
use text_range::{Point, TextRange};
use thiserror::Error;
use uuid::Uuid;
use vector_payload::{Embedding, Payload, SymbolPayload};

pub struct SemanticIndex {
    tokenizer: tokenizers::Tokenizer,
    overlap: chunking::OverlapStrategy,
    session: ort::Session,
    qdrantPayload: Vec<PointStruct>,
    qdrantSymbolPayload: Vec<PointStruct>,
    counter: usize,
}
use crate::{COLLECTION_NAME, COLLECTION_NAME_SYMBOLS};
#[derive(Error, Debug)]
pub enum SemanticError {
    /// Represents failure to initialize Qdrant client
    #[error("Qdrant initialization failed. Is Qdrant running on `qdrant-url`?")]
    QdrantInitializationError,

    #[error("ONNX runtime error")]
    OnnxRuntimeError {
        #[from]
        error: ort::Error,
    },

    #[error("semantic error")]
    Anyhow {
        #[from]
        error: anyhow::Error,
    },
}

#[derive(Debug)]
pub enum CommitError {
    QdrantError,
    NoQdrantClient, // Add other error variants as needed
}

impl fmt::Display for CommitError {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        match *self {
            CommitError::QdrantError => write!(f, "Error with Qdrant"),
            CommitError::NoQdrantClient => write!(f, "No Qdrant client available"),
            // ... match other variants and write an appropriate message
        }
    }
}

impl Error for CommitError {
    // This trait can often remain empty; it's mainly here to ensure compatibility
    // with the broader Error trait.
}

impl SemanticIndex {
    pub fn new(counter: &usize) -> Result<Self, anyhow::Error> {
        let threads: usize = 1;
        let env = ort::init()
            .with_execution_providers([CPUExecutionProvider::default().build()])
            .commit()
            .map_err(anyhow::Error::from)?;

        let environment = Arc::new(env);

        // Explicitly handle the error and convert it to anyhow::Error
        // append tokenizer.json to the model path from get_model_path() function
        // use path join to construct full path 
        let tokenizer_path = std::path::PathBuf::from(get_model_path())
        .join("tokenizer.json")
        .to_string_lossy()
        .to_string();

        let tokenizer = tokenizers::Tokenizer::from_file(
            tokenizer_path
        )
        .map_err(|e| {
            let error_message = e.to_string(); // Extract the error message
            log::error!("Error creating tokenizer: {}", error_message); // Optional: log the error
            anyhow::Error::msg(error_message) // Create an anyhow::Error with the message
        })?;

        let onnx_path = std::path::PathBuf::from(get_model_path())
        .join("model.onnx")
        .to_string_lossy()
        .to_string();

        let session = Session::builder()?
            .commit_from_file(onnx_path)
            .map_err(anyhow::Error::from)?;

        Ok(Self {
            tokenizer: tokenizer.into(),
            overlap: chunking::OverlapStrategy::default(),
            session: session.into(),
            qdrantPayload: Vec::new(),
            qdrantSymbolPayload: Vec::new(),
            counter: *counter,
        })
    }

    pub fn overlap_strategy(&self) -> chunking::OverlapStrategy {
        self.overlap
    }

    pub fn embed(&self, sequence: &str) -> anyhow::Result<Embedding> {
        let tokenizer_output = self.tokenizer.encode(sequence, true).unwrap();

        let input_ids = tokenizer_output.get_ids();
        let attention_mask = tokenizer_output.get_attention_mask();
        let token_type_ids = tokenizer_output.get_type_ids();
        let length = input_ids.len();
        trace!("embedding {} tokens {:?}", length, sequence);

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

    pub async fn tokenize_and_commit<'a>(
        &mut self,
        buffer: &'a str,
        repo_name: &'a str,
        path: &str,
        semantic_hash: &str,
        lang_str: &str,
        qdrant_client: &Option<QdrantClient>,
    ) -> Result<(), Box<dyn std::error::Error>> {
        // Tokenize
        let chunks = self.tokenize_chunk(
            buffer,
            repo_name,
            path,
            semantic_hash,
            50..256,
            qdrant_client,
        );

        // Commit
        self.commit_chunks(
            chunks,
            repo_name,
            path,
            semantic_hash,
            lang_str,
            qdrant_client,
        )
        .await
    }

    // takes the hash map containing the symbol metadata and commits it to the qdrant database.
    // the key of the hash map where the key primarily contains
    pub async fn commit_symbol_metadata(
        &mut self,
        symbol_meta_hash_map: &HashMap<SymbolKey, Vec<SymbolValue>>,
        qdrant_client: &Option<QdrantClient>,
    ) -> Result<(), Box<dyn std::error::Error>> {
        //let mut temp_payloads = Vec::new();

        let embedder = |c: &str| {
            debug!("generating embedding");
            self.embed(c)
        };

        // iterate through the symbolMeta hashmap and create SymbolPayload from the symbolMeta hashmap.

        let mut symbol_meta_payload: Vec<PointStruct> = symbol_meta_hash_map
            .iter()
            .map(|(key, values)| {
                // iterate the values and create the vectors containing relative paths, start_bytes, end_bytes, and is_global.
                // is_global is a vector of bools which signifies whether the symbol is declared in the root scope or not.
                // relative_paths is a vector of strings which signifies the relative path of the file in which the symbol is declared.
                // start_bytes and end_bytes are vectors of i64 which signifies the start and end bytes of the symbol in the file.
                let (
                    start_bytes,
                    end_bytes,
                    relative_paths,
                    is_global_vec,
                    language_ids,
                    symbol_types,
                    node_kinds,
                ) = values.iter().fold(
                    (
                        Vec::new(),
                        Vec::new(),
                        Vec::new(),
                        Vec::new(),
                        Vec::new(),
                        Vec::new(),
                        Vec::new(),
                    ),
                    |(
                        mut start_acc,
                        mut end_acc,
                        mut paths_acc,
                        mut global_acc,
                        mut language_ids,
                        mut symbol_types,
                        mut node_kinds,
                    ),
                     value| {
                        start_acc.push(value.start_byte as i64);
                        end_acc.push(value.end_byte as i64);
                        paths_acc.push(value.relative_path.clone());
                        global_acc.push(value.is_global);
                        language_ids.push(value.language_id.clone());
                        symbol_types.push(value.symbol_type.clone());
                        node_kinds.push(value.node_kind.clone());

                        (
                            start_acc,
                            end_acc,
                            paths_acc,
                            global_acc,
                            language_ids,
                            symbol_types,
                            node_kinds,
                        )
                    },
                );

                // create the SymbolPayload from the key and the vectors created above.
                // this format is required by qdrant.
                let mut symbol_qdrant_meta = SymbolPayload {
                    lang_ids: language_ids,
                    repo_name: key.repo_name.clone(),
                    symbol: key.symbol.clone(),
                    symbol_types: symbol_types,
                    is_globals: is_global_vec,
                    start_bytes: start_bytes,
                    end_bytes: end_bytes,
                    relative_paths: relative_paths,
                    node_kinds: node_kinds,
                    ..Default::default()
                };

                let id = Uuid::new_v4();
                println!("id: {}", id);
                // we find the embedding vector using the symbol from the ast.
                return PointStruct {
                    id: Some(PointId::from(id.to_string())),
                    vectors: Some(embedder(&key.symbol).unwrap().into()),
                    payload: symbol_qdrant_meta.convert_to__qdrant_fields(),
                };
            })
            .collect();

        println!("finished iterating on the chuks and creating temp payload");

        //self.qdrantPayload.extend(symbol_meta_payload);
        // print length of the payload
        println!("length of the payload: {}", symbol_meta_payload.len());

        // commit the data to Qdrant.
        let new: Vec<_> = std::mem::take(symbol_meta_payload.as_mut());

        // qdrant doesn't like empty payloads.
        if let Some(ref client) = qdrant_client {
            // qdrant doesn't like empty payloads.
            if !new.is_empty() {
                println!("Just before committing to the database.");
                client
                    .upsert_points_batch(COLLECTION_NAME_SYMBOLS, new, None, 10)
                    .await
                    .map_err(|_| Box::new(CommitError::QdrantError))?;
            }
            println!("finished committing symbol to qdrant");
        } else {
            // Handle the case where qdrant_client is None if necessary
            return Err(Box::new(CommitError::NoQdrantClient));
        }
        // sleep for 3 seconds if counter % 10 is 0.
        // TODO: remove this once we have a better way to handle this.
        // if self.counter % 9 == 0 {
        //     println!("sleeping for 4 seconds: {}", self.counter);
        //     std::thread::sleep(std::time::Duration::from_secs(4));
        // }
        // if self.counter % 69 == 0 {
        //     println!("sleeping for 20 seconds: {}", self.counter);
        //     std::thread::sleep(std::time::Duration::from_secs(20));
        // }
        Ok(())
    }

    pub async fn commit_chunks<'s>(
        &mut self,
        chunks: Vec<Chunk<'_>>,
        repo_name: &'s str,
        relative_path: &str,
        semanticHash: &str,
        lang_str: &str,
        qdrant_client: &Option<QdrantClient>,
    ) -> Result<(), Box<dyn std::error::Error>> {
        let mut temp_payloads = Vec::new();

        let embedder = |c: &str| {
            debug!("generating embedding");
            self.embed(c)
        };
        chunks.iter().for_each(|chunk| {
            let data = format!("{repo_name}\t{relative_path}\n{}", chunk.data,);
            let payload = Payload {
                repo_name: repo_name.to_owned(),
                relative_path: relative_path.to_owned(),
                content_hash: semanticHash.to_string(),
                text: chunk.data.to_owned(),
                lang: lang_str.to_ascii_lowercase(),
                start_line: chunk.range.start.line as u64,
                end_line: chunk.range.end.line as u64,
                start_byte: chunk.range.start.byte as u64,
                end_byte: chunk.range.end.byte as u64,
                ..Default::default()
            };

            let id = Uuid::new_v4();
            println!("id: {}", id);
            let qdrant_payload = PointStruct {
                id: Some(PointId::from(id.to_string())),
                vectors: Some(embedder(chunk.data).unwrap().into()),
                payload: payload.convert_to__qdrant_fields(),
            };

            temp_payloads.push(qdrant_payload);
        });
        println!("finished iterating on the chuks and creating temp payload");

        // self.qdrantPayload.extend(temp_payloads);
        // print length of the payload
        println!("length of the payload: {}", temp_payloads.len());

        // commit the data to Qdrant.
        let new: Vec<_> = std::mem::take(temp_payloads.as_mut());

        // qdrant doesn't like empty payloads.
        if let Some(ref client) = qdrant_client {
            // qdrant doesn't like empty payloads.
            if !new.is_empty() {
                println!("Just before committing to the database.");
                client
                    .upsert_points_batch(COLLECTION_NAME, new, None, 10)
                    .await
                    .map_err(|_| Box::new(CommitError::QdrantError))?;
            }
            println!("finished committing to qdrant");
        } else {
            // Handle the case where qdrant_client is None if necessary
            return Err(Box::new(CommitError::NoQdrantClient));
        }
        // sleep for 3 seconds if counter % 10 is 0.
        // TODO: remove this once we have a better way to handle this.
        // if self.counter % 9 == 0 {
        //     println!("sleeping for 4 seconds: {}", self.counter);
        //     std::thread::sleep(std::time::Duration::from_secs(4));
        // }
        // if self.counter % 69 == 0 {
        //     println!("sleeping for 20 seconds: {}", self.counter);
        //     std::thread::sleep(std::time::Duration::from_secs(20));
        // }
        Ok(())
    }

    pub fn tokenize_chunk<'s>(
        &self,
        src: &'s str,
        repo_name: &'s str,
        file: &str,
        semanticHash: &str,
        token_bounds: Range<usize>,
        qdrant_client: &Option<QdrantClient>,
    ) -> Vec<Chunk<'s>> {
        if self.tokenizer.get_padding().is_some() || self.tokenizer.get_truncation().is_some() {
            error!(
                "This code can panic if padding and truncation are not turned off. Please make sure padding is off."
            );
        }
        let min_tokens = token_bounds.start;
        // no need to even tokenize files too small to contain our min number of tokens
        if src.len() < min_tokens {
            println!("Skipping \"{}\" because it is too small", src);
            return Vec::new();
        }
        let Ok(encoding) = self.tokenizer.encode(src, true) else {
            warn!("Could not encode \"{}\"", src);
            return Vec::new();
        };

        let offsets = encoding.get_offsets();
        // again, if we have less than our minimum number of tokens, we may skip the file

        if offsets.len() < min_tokens {
            return Vec::new();
        }

        let repo_plus_file = repo_name.to_owned() + "\t" + file + "\n";
        let repo_tokens = match self.tokenizer.encode(repo_plus_file, true) {
            Ok(encoding) => encoding.get_ids().len(),
            Err(e) => {
                error!("failure during encoding repo + file {:?}", e);
                return Vec::new();
            }
        };

        if token_bounds.end <= DEDUCT_SPECIAL_TOKENS + repo_tokens {
            error!("too few tokens");
            return Vec::new();
        }

        let max_tokens = token_bounds.end - DEDUCT_SPECIAL_TOKENS - repo_tokens;
        let max_newline_tokens = max_tokens * 3 / 4; //TODO: make this configurable
        let max_boundary_tokens = max_tokens * 7 / 8; //TODO: make this configurable
        debug!("max tokens reduced to {max_tokens}");

        let offsets_len = offsets.len() - 1;
        // remove the SEP token which has (0, 0) offsets for some reason
        let offsets = if offsets[offsets_len].0 == 0 {
            &offsets[..offsets_len]
        } else {
            offsets
        };
        let ids = encoding.get_ids();
        let mut chunks = Vec::new();
        let mut start = 0;
        let (mut last_line, mut last_byte) = (0, 0);
        loop {
            let next_limit = start + max_tokens;
            let end_limit = if next_limit >= offsets_len {
                offsets_len
            } else if let Some(next_newline) = (start + max_newline_tokens..next_limit)
                .rfind(|&i| src[offsets[i].0..offsets[i + 1].0].contains('\n'))
            {
                next_newline
            } else if let Some(next_boundary) =
                (start + max_boundary_tokens..next_limit).rfind(|&i| {
                    !self
                        .tokenizer
                        .id_to_token(ids[i + 1])
                        .map_or(false, |s| s.starts_with("##"))
                })
            {
                next_boundary
            } else {
                next_limit
            };
            if end_limit - start >= min_tokens {
                add_token_range(
                    &mut chunks,
                    src,
                    offsets,
                    start..end_limit + 1,
                    &mut last_line,
                    &mut last_byte,
                );
            }
            if end_limit == offsets_len {
                return chunks;
            }
            let diff = self.overlap.next_subdivision(end_limit - start);
            let mid = start + diff;
            // find nearest newlines or boundaries, set start accordingly
            let next_newline_diff =
                (mid..end_limit).find(|&i| src[offsets[i].0..offsets[i + 1].0].contains('\n'));
            let prev_newline_diff = (start + (diff / 2)..mid)
                .rfind(|&i| src[offsets[i].0..offsets[i + 1].0].contains('\n'))
                .map(|t| t + 1);
            start = match (next_newline_diff, prev_newline_diff) {
                (Some(n), None) | (None, Some(n)) => n,
                (Some(n), Some(p)) => {
                    if n - mid < mid - p {
                        n
                    } else {
                        p
                    }
                }
                (None, None) => (mid..end_limit)
                    .find(|&i| {
                        !self
                            .tokenizer
                            .id_to_token(ids[i + 1])
                            .map_or(false, |s| s.starts_with("##"))
                    })
                    .unwrap_or(mid),
            };
        }
    }

    pub fn by_lines(src: &str, size: usize) -> Vec<Chunk<'_>> {
        let ends = std::iter::once(0)
            .chain(src.match_indices('\n').map(|(i, _)| i))
            .enumerate()
            .collect::<Vec<_>>();

        let s = ends.iter().copied();
        let last = src.len().saturating_sub(1);
        let last_line = *ends.last().map(|(idx, _)| idx).unwrap_or(&0);

        ends.iter()
            .copied()
            .step_by(size)
            .zip(s.step_by(size).skip(1).chain([(last_line, last)]))
            .filter(|((_, start_byte), (_, end_byte))| start_byte < end_byte)
            .map(|((start_line, start_byte), (end_line, end_byte))| Chunk {
                data: &src[start_byte..end_byte],
                range: TextRange {
                    start: Point {
                        byte: start_byte,
                        line: start_line,
                        column: 0,
                    },
                    end: Point {
                        byte: end_byte,
                        line: end_line,
                        column: 0,
                    },
                },
            })
            .collect()
    }
}
