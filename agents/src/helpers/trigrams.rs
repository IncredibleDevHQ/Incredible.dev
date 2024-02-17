use std::{
    borrow::Cow,
    collections::{HashMap, HashSet},
    mem,
};

use compact_str::CompactString;
use smallvec::SmallVec;

/// Split a string into trigrams, returning a bigram or unigram if the string is shorter than 3
/// characters.
pub fn trigrams(s: &str) -> impl Iterator<Item = CompactString> {
    let mut chars = s.chars().collect::<SmallVec<[char; 6]>>();

    std::iter::from_fn(move || match chars.len() {
        0 => None,
        1 | 2 | 3 => Some(mem::take(&mut chars).into_iter().collect()),
        _ => {
            let out = chars.iter().take(3).collect();
            chars.remove(0);
            Some(out)
        }
    })
}
