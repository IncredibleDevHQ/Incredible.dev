use hyperpolyglot::detect_buffer;
use std::{io::Cursor, path::Path};

// Detects the language of the given file.
pub fn detect_language(path: &Path, buf: &[u8]) -> Option<&'static str> {
    detect_buffer(path, |_| Ok(Cursor::new(buf)))
        .ok()
        .flatten()
        .map(|d| d.language())
}
