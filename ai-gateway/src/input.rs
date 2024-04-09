use crate::client::ModelCapabilities;
use crate::utils::sha256sum;

use anyhow::{bail, Context, Result};
use base64::{self, engine::general_purpose::STANDARD, Engine};
use fancy_regex::Regex;
use lazy_static::lazy_static;
use mime_guess::from_path;
use std::{
    collections::HashMap,
    fs::{self, File},
    io::Read,
    path::{Path, PathBuf},
};
use unicode_width::{UnicodeWidthChar, UnicodeWidthStr};

use crate::message::message::Message;
use super::function_calling::Function;

const IMAGE_EXTS: [&str; 5] = ["png", "jpeg", "jpg", "webp", "gif"];

lazy_static! {
    static ref URL_RE: Regex = Regex::new(r"^[A-Za-z0-9_-]{2,}:/").unwrap();
}

#[derive(Debug, Clone)]
pub struct Input {
    text: String,
    functions: Option<Vec<Function>>,
    history: Option<Vec<Message>>,
}

impl Input {
    pub fn from_str(text: &str) -> Self {
        Self {
            text: text.to_string(),
            functions: Default::default(),
            history: Default::default(),
        }
    }

    pub fn new(
        text: &str,
        functions: Option<Vec<Function>>,
        history: Option<Vec<Message>>,
    ) -> Self {
        Self {
            text: text.to_string(),
            functions,
            history,
        }
    }

    pub fn is_empty(&self) -> bool {
        self.text.is_empty()
    }

    pub fn history_exists(&self) -> bool {
        self.history.is_some()
    }

    pub fn get_history(&self) -> Option<Vec<Message>> {
        self.history.clone()
    }

    pub fn function_calls_exists(&self) -> bool {
        self.functions.is_some()
    }

    pub fn function_calls(&self) -> Option<Vec<Function>> {
        self.functions.clone()
    }

    pub fn summary(&self) -> String {
        let text: String = self
            .text
            .trim()
            .chars()
            .map(|c| if c.is_control() { ' ' } else { c })
            .collect();
        if text.width_cjk() > 70 {
            let mut sum_width = 0;
            let mut chars = vec![];
            for c in text.chars() {
                sum_width += c.width_cjk().unwrap_or(1);
                if sum_width > 67 {
                    chars.extend(['.', '.', '.']);
                    break;
                }
                chars.push(c);
            }
            chars.into_iter().collect()
        } else {
            text
        }
    }

    pub fn render(&self) -> String {
        self.text.clone()
    }

    pub fn to_message(&self) -> String {
        self.text.clone()
    }

    // Without media, we assume only text capabilities are needed.
    pub fn required_capabilities(&self) -> ModelCapabilities {
        ModelCapabilities::Text
    }
}

fn resolve_path(file: &str) -> Option<PathBuf> {
    if let Ok(true) = URL_RE.is_match(file) {
        return None;
    }
    let path = if let (Some(file), Some(home)) = (file.strip_prefix('~'), dirs::home_dir()) {
        home.join(file)
    } else {
        std::env::current_dir().ok()?.join(file)
    };
    Some(path)
}

fn is_image_ext(path: &Path) -> bool {
    path.extension()
        .map(|v| {
            IMAGE_EXTS
                .iter()
                .any(|ext| *ext == v.to_string_lossy().to_lowercase())
        })
        .unwrap_or_default()
}

fn read_media_to_data_url<P: AsRef<Path>>(image_path: P) -> Result<String> {
    let mime_type = from_path(&image_path).first_or_octet_stream().to_string();

    let mut file = File::open(image_path)?;
    let mut buffer = Vec::new();
    file.read_to_end(&mut buffer)?;

    let encoded_image = STANDARD.encode(buffer);
    let data_url = format!("data:{};base64,{}", mime_type, encoded_image);

    Ok(data_url)
}
