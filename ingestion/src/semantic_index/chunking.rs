use crate::semantic_index::text_range::{Point, TextRange};
extern crate clap;
use clap::builder::PossibleValue;
// use range
use serde::{Deserialize, Serialize};
use std::fmt::Display;
use std::fmt::Write;
use std::ops::Range;
// A Chunk type, containing the plain text (borrowed from the source)
/// and a `TextRange` with byte, line and column positions
#[derive(Debug)]
pub struct Chunk<'a> {
    pub data: &'a str,
    pub range: TextRange,
}

// Parse arguments into enums.
///
/// When deriving [`Parser`], a field whose type implements `ValueEnum` can have the attribute
/// `#[arg(value_enum)]` which will
/// - Call [`EnumValueParser`][crate::builder::EnumValueParser]
/// - Allowing using the `#[arg(default_value_t)]` attribute without implementing `Display`.
///
/// **NOTE:** Deriving requires the `derive` feature flag
pub trait ValueEnum: Sized + Clone {
    /// All possible argument values, in display order.
    fn value_variants<'a>() -> &'a [Self];

    /// Parse an argument into `Self`.
    fn from_str(input: &str, ignore_case: bool) -> Result<Self, String> {
        Self::value_variants()
            .iter()
            .find(|v| {
                v.to_possible_value()
                    .expect("ValueEnum::value_variants contains only values with a corresponding ValueEnum::to_possible_value")
                    .matches(input, ignore_case)
            })
            .cloned()
            .ok_or_else(|| format!("invalid variant: {input}"))
    }

    /// The canonical argument value.
    ///
    /// The value is `None` for skipped variants.
    fn to_possible_value(&self) -> Option<PossibleValue>;
}

impl<'a> Chunk<'a> {
    pub fn new(data: &'a str, start: Point, end: Point) -> Self {
        Self {
            data,
            range: TextRange { start, end },
        }
    }

    pub fn len(&self) -> usize {
        self.data.len()
    }

    pub fn is_empty(&self) -> bool {
        self.data.len() < 1
    }
}

// The strategy for overlapping chunks
#[derive(Copy, Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(try_from = "&str", into = "String")]
pub enum OverlapStrategy {
    /// go back _ lines from the end
    ByLines(usize),
    /// A value > 0 and < 1 that indicates the target overlap in tokens.
    Partial(f64),
}

impl Display for OverlapStrategy {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::ByLines(n) => n.fmt(f),
            Self::Partial(p) => {
                (*p / 100.0).fmt(f)?;
                f.write_char('%')
            }
        }
    }
}

impl From<OverlapStrategy> for String {
    fn from(val: OverlapStrategy) -> Self {
        val.to_string()
    }
}

static OVERLAP_STRATEGY_VARIANTS: &[OverlapStrategy] =
    &[OverlapStrategy::ByLines(1), OverlapStrategy::Partial(0.5)];

impl ValueEnum for OverlapStrategy {
    fn value_variants<'a>() -> &'a [Self] {
        OVERLAP_STRATEGY_VARIANTS
    }

    fn to_possible_value(&self) -> Option<PossibleValue> {
        if self == &OVERLAP_STRATEGY_VARIANTS[0] {
            Some(PossibleValue::new("1"))
        } else if self == &OVERLAP_STRATEGY_VARIANTS[1] {
            Some(PossibleValue::new("50%"))
        } else {
            None
        }
    }

    fn from_str(input: &str, _ignore_case: bool) -> Result<Self, String> {
        Self::try_from(input)
            .map_err(|_| String::from("overlap should be a number of lines or a percentage"))
    }
}

impl TryFrom<&'_ str> for OverlapStrategy {
    type Error = &'static str;

    fn try_from(input: &str) -> Result<Self, &'static str> {
        Ok(if let Some(percentage) = input.strip_suffix('%') {
            Self::Partial(
                str::parse::<f64>(percentage).map_err(|_| "failure parsing overlap strategy")?
                    * 0.01,
            )
        } else {
            Self::ByLines(str::parse(input).map_err(|_| "failure parsing overlap strategy")?)
        })
    }
}

impl OverlapStrategy {
    // returns the next startpoint for overlong lines
    pub fn next_subdivision(&self, max_tokens: usize) -> usize {
        (match self {
            OverlapStrategy::ByLines(n) => max_tokens - n,
            OverlapStrategy::Partial(part) => ((max_tokens as f64) * part) as usize,
        })
        .max(1) // ensure we make forward progress
    }
}

impl Default for OverlapStrategy {
    fn default() -> Self {
        Self::Partial(0.5)
    }
}

/// This should take care of [CLS], [SEP] etc. which could be introduced during per-chunk tokenization
pub const DEDUCT_SPECIAL_TOKENS: usize = 2;

pub fn add_token_range<'s>(
    chunks: &mut Vec<Chunk<'s>>,
    src: &'s str,
    offsets: &[(usize, usize)],
    o: Range<usize>,
    last_line: &mut usize,
    last_byte: &mut usize,
) {
    let start_byte = offsets[o.start].0;
    let end_byte = offsets.get(o.end).map_or(src.len(), |&(s, _)| s);

    if end_byte <= start_byte {
        return;
    }

    debug_assert!(
        o.end - o.start < 256,
        "chunk too large: {} tokens in {:?} bytes {:?}",
        o.end - o.start,
        o,
        start_byte..end_byte
    );

    let start = point(src, start_byte, *last_line, *last_byte);
    let end = point(src, end_byte, *last_line, *last_byte);
    (*last_line, *last_byte) = (start.line, start.byte);
    chunks.push(Chunk::new(&src[start_byte..end_byte], start, end));
}

/// This calculates the line and column for a given byte position. The last_line and last_byte
/// parameters can be used to reduce the amount of searching for the line position from quadratic
/// to linear. If in doubt, just use `0` for last_line and `0` for last_byte.
///
/// # Examples
///
/// ```no_run
/// assert_eq!(
///     bleep::semantic::chunk::point("fn hello() {\n    \"world\"\n}\n", 16, 0, 0),
///     bleep::text_range::Point::new(16, 1, 4)
/// );
/// ```
pub fn point(src: &str, byte: usize, last_line: usize, last_byte: usize) -> Point {
    assert!(
        byte >= last_byte,
        "byte={byte} < last_byte={last_byte}, last_line={last_line}"
    );
    let line = src.as_bytes()[last_byte..byte]
        .iter()
        .filter(|&&b| b == b'\n')
        .count()
        + last_line;
    let column = if let Some(last_nl) = src[..byte].rfind('\n') {
        byte - last_nl
    } else {
        byte
    };
    Point { byte, column, line }
}
