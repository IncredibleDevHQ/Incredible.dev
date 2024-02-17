use regex::Regex;
use std::borrow::Cow;

#[derive(Debug, PartialEq, Eq, Clone, Hash, serde::Serialize, serde::Deserialize)]
pub enum Literal<'a> {
    Plain(Cow<'a, str>),
    Regex(Cow<'a, str>),
}

impl From<&String> for Literal<'static> {
    fn from(value: &String) -> Self {
        Literal::Plain(value.to_owned().into())
    }
}

impl<'a> Default for Literal<'a> {
    fn default() -> Self {
        Self::Plain(Cow::Borrowed(""))
    }
}

impl<'a> Literal<'a> {
    fn join_as_regex(self, rhs: Self) -> Self {
        let lhs = self.regex_str();
        let rhs = rhs.regex_str();
        Self::Regex(Cow::Owned(format!("{lhs}\\s+{rhs}")))
    }

    fn join_as_plain(self, rhs: Self) -> Option<Self> {
        let lhs = self.as_plain()?;
        let rhs = rhs.as_plain()?;
        Some(Self::Plain(Cow::Owned(format!("{lhs} {rhs}"))))
    }

    /// Convert this literal into a regex string.
    ///
    /// If this literal is a regex, it is returned as-is. If it is a plain text literal, it is
    /// escaped first before returning.
    pub fn regex_str(&self) -> Cow<'a, str> {
        match self {
            Self::Plain(text) => regex::escape(text).into(),
            Self::Regex(r) => r.clone(),
        }
    }

    pub fn regex(&self) -> Result<Regex, regex::Error> {
        Regex::new(&self.regex_str())
    }

    pub fn as_plain(&self) -> Option<Cow<'a, str>> {
        match self {
            Self::Plain(p) => Some(p.clone()),
            Self::Regex(..) => None,
        }
    }

    /// Force this literal into the `Regex` variant.
    fn make_regex(&mut self) {
        *self = match std::mem::take(self) {
            Self::Plain(s) | Self::Regex(s) => Self::Regex(s),
        }
    }

    pub fn unwrap(self) -> Cow<'a, str> {
        match self {
            Literal::Plain(v) => v,
            Literal::Regex(v) => v,
        }
    }

    pub fn into_owned(self) -> Literal<'static> {
        match self {
            Literal::Plain(cow) => Literal::Plain(Cow::Owned(cow.into_owned())),
            Literal::Regex(cow) => Literal::Regex(Cow::Owned(cow.into_owned())),
        }
    }
}
