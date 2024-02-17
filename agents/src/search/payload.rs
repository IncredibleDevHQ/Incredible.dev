// import all the necessary modules.
use std::{borrow::Cow, collections::HashMap, str};

use qdrant_client::{
    prelude::{QdrantClient, QdrantClientConfig},
    qdrant::{point_id::PointIdOptions, vectors::VectorsOptions, PointId, Vectors,Value,  ScoredPoint},
};

pub type Embedding = Vec<f32>;


// Payload format to write and deserialize data in and from qdrant.
#[derive(Default, Clone, Debug, serde::Deserialize, serde::Serialize)]
pub struct SymbolPayload {

    pub repo_name: String,
    pub symbol: String,

    
    pub symbol_types: Vec<String>,
    pub lang_ids: Vec<String>,
    pub is_globals: Vec<bool>, 
    pub start_bytes: Vec<i64>,
    pub end_bytes: Vec<i64>,
    pub relative_paths: Vec<String>,
    pub node_kinds: Vec<String>,

    #[serde(skip)]
    pub id: Option<String>,
    #[serde(skip)]
    pub embedding: Option<Embedding>,
    #[serde(skip)]
    pub score: Option<f32>,
}

// metadata to extract code chunks from scope graph 
#[derive(Default, Clone, Debug, serde::Deserialize, serde::Serialize)]
pub struct CodeExtractMeta {
    pub is_global: bool,
    pub start_byte: i64,
    pub end_byte: i64,
    pub node_kind: String,
    pub symbol_type: String,
    pub symbol: String,
    pub score: f32,
}

#[derive(Default, Clone, Debug, serde::Deserialize, serde::Serialize)]
pub struct PathExtractMeta {
    pub path: String,
    pub score: f32,
    pub history: Vec<String>,
    pub code_extract_meta: Vec<CodeExtractMeta>,
}

impl SymbolPayload {
    pub fn from_qdrant(orig: ScoredPoint) -> SymbolPayload {
        let ScoredPoint {
            id,
            payload,
            score,
            vectors,
            ..
        } = orig;

        parse_symbol_payload(id, vectors, payload, score)
    }
}

fn parse_symbol_payload(
    id: Option<PointId>,
    vectors: Option<Vectors>,
    payload: HashMap<String, Value>,
    score: f32,
) -> SymbolPayload {
    let Some(PointId {
        point_id_options: Some(PointIdOptions::Uuid(id)),
    }) = id
    else {
        // unless the db was corrupted/written by someone else,
        // this shouldn't happen
        unreachable!("corrupted db");
    };

    let embedding = match vectors {
        None => None,
        Some(Vectors {
            vectors_options: Some(VectorsOptions::Vector(v)),
        }) => Some(v.data),
        _ => {
            // this also should probably never happen
            unreachable!("got non-vector value");
        }
    };

    let mut converted = payload
        .into_iter()
        .map(|(key, value)| (key, kind_to_value(value.kind)))
        .collect::<HashMap<String, serde_json::Value>>();

    SymbolPayload {
        repo_name: val_str!(converted, "repo_name"),
        symbol: val_str!(converted, "symbol"),
        symbol_types: val_str!(converted, "symbol_type"),
        lang_ids: val_str!(converted, "lang"),
        is_globals: val_str!(converted, "is_global"),
        start_bytes: val_str!(converted, "start_byte"),
        end_bytes: val_str!(converted, "end_byte"),
        relative_paths: val_str!(converted, "relative_path"),
        node_kinds: val_str!(converted, "node_kind"),
        id: Some(id),
        score: Some(score),
        embedding,
    }
}


#[derive(Default, Clone, Debug, serde::Deserialize, serde::Serialize)]
pub struct Payload {
    pub lang: String,
    pub repo_name: String,
    pub relative_path: String,
    pub content_hash: String,
    pub text: String,
    pub start_line: u64,
    pub end_line: u64,
    pub start_byte: u64,
    pub end_byte: u64,

    #[serde(skip)]
    pub id: Option<String>,
    #[serde(skip)]
    pub embedding: Option<Embedding>,
    #[serde(skip)]
    pub score: Option<f32>,
}

impl Payload {
    pub fn from_qdrant(orig: ScoredPoint) -> Payload {
        let ScoredPoint {
            id,
            payload,
            score,
            vectors,
            ..
        } = orig;

        parse_payload(id, vectors, payload, score)
    }
}


impl PartialEq for Payload {
    fn eq(&self, other: &Self) -> bool {
        self.lang == other.lang
            && self.repo_name == other.repo_name
            && self.relative_path == other.relative_path
            && self.content_hash == other.content_hash
            && self.text == other.text
            && self.start_line == other.start_line
            && self.end_line == other.end_line
            && self.start_byte == other.start_byte
            && self.end_byte == other.end_byte

        // ignoring deserialized fields that will not exist on a newly
        // created payload
    }
}

macro_rules! val_str(($hash:ident, $val:expr) => { serde_json::from_value($hash.remove($val).unwrap()).unwrap() });
macro_rules! val_parse_str(($hash:ident, $val:expr) => {
    serde_json::from_value::<Cow<'_, str>>($hash.remove($val).unwrap())
        .unwrap()
        .parse()
        .unwrap()
});
pub(crate) use val_str; 

fn kind_to_value(kind: Option<qdrant_client::qdrant::value::Kind>) -> serde_json::Value {
    use qdrant_client::qdrant::value::Kind;
    match kind {
        Some(Kind::NullValue(_)) => serde_json::Value::Null,
        Some(Kind::BoolValue(v)) => serde_json::Value::Bool(v),
        Some(Kind::DoubleValue(v)) => {
            serde_json::Value::Number(serde_json::Number::from_f64(v).unwrap())
        }
        Some(Kind::IntegerValue(v)) => serde_json::Value::Number(v.into()),
        Some(Kind::StringValue(v)) => serde_json::Value::String(v),
        Some(Kind::ListValue(v)) => serde_json::Value::Array(
            v.values
                .into_iter()
                .map(|v| kind_to_value(v.kind))
                .collect(),
        ),
        Some(Kind::StructValue(_v)) => todo!(),
        None => serde_json::Value::Null,
    }
}

fn parse_payload(
    id: Option<PointId>,
    vectors: Option<Vectors>,
    payload: HashMap<String, Value>,
    score: f32,
) -> Payload {
    let Some(PointId {
        point_id_options: Some(PointIdOptions::Uuid(id)),
    }) = id
    else {
        // unless the db was corrupted/written by someone else,
        // this shouldn't happen
        unreachable!("corrupted db");
    };

    let embedding = match vectors {
        None => None,
        Some(Vectors {
            vectors_options: Some(VectorsOptions::Vector(v)),
        }) => Some(v.data),
        _ => {
            // this also should probably never happen
            unreachable!("got non-vector value");
        }
    };

    let mut converted = payload
        .into_iter()
        .map(|(key, value)| (key, kind_to_value(value.kind)))
        .collect::<HashMap<String, serde_json::Value>>();

    Payload {
        lang: val_str!(converted, "lang"),
        repo_name: val_str!(converted, "repo_name"),
        relative_path: val_str!(converted, "relative_path"),
        content_hash: val_str!(converted, "content_hash"),
        text: val_str!(converted, "snippet"),
        start_line: val_parse_str!(converted, "start_line"),
        end_line: val_parse_str!(converted, "end_line"),
        start_byte: val_parse_str!(converted, "start_byte"),
        end_byte: val_parse_str!(converted, "end_byte"),

        id: Some(id),
        score: Some(score),
        embedding,
    }
}
