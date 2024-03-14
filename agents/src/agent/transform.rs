use serde_json::de;
use anyhow::{Context, Result};
use std::borrow::Cow;
use regex::Regex;
use comrak::nodes::{NodeValue, NodeHtmlBlock};
use tiktoken_rs;
use tiktoken_rs::CoreBPE;
use lazy_regex::regex;
use std::collections::HashMap;
use std::mem;
use serde::Deserialize;


#[derive(serde::Deserialize, Debug)]
enum CodeChunk {
    QuotedCode {
        #[serde(default, rename = "Code")]
        code: String,
        #[serde(default, rename = "Language")]
        language: String,
        #[serde(default, rename = "Path")]
        path: String,
        #[serde(default, rename = "StartLine", deserialize_with = "deserialize_lineno")]
        start_line: Option<u32>,
        #[serde(default, rename = "EndLine", deserialize_with = "deserialize_lineno")]
        end_line: Option<u32>,
    },
    GeneratedCode {
        #[serde(default, rename = "Code")]
        code: String,
        #[serde(default, rename = "Language")]
        language: String,
    },
}



impl CodeChunk {
    fn to_markdown(&self) -> String {
        let (ty, code, lang, path, start, end) = match self {
            CodeChunk::QuotedCode {
                code,
                language,
                path,
                start_line,
                end_line,
            } => (
                "Quoted",
                code,
                language,
                path.as_str(),
                start_line.map(|n| n.saturating_sub(1)),
                end_line.map(|n| n.saturating_sub(1)),
            ),
            CodeChunk::GeneratedCode { code, language } => {
                ("Generated", code, language, "", None, None)
            }
        };

        format!(
            "```type:{ty},lang:{lang},path:{path},lines:{}-{}\n{code}\n```",
            start.unwrap_or(0),
            end.unwrap_or(0)
        )
    }
}


fn deserialize_lineno<'a, D: serde::Deserializer<'a>>(de: D) -> Result<Option<u32>, D::Error> {
    let opt = Option::deserialize(de)?;
    let opt = opt.and_then(|s: String| {
        if s.is_empty() {
            Some(0)
        } else {
            s.parse().ok()
        }
    });

    Ok(opt)
}


fn try_trim_code_xml(xml: &str) -> Result<String> {
    let xml = fixup_xml_code(xml);

    let code_chunk = de::from_str(&xml).context("couldn't parse as XML code block")?;

    Ok(match code_chunk {
        CodeChunk::QuotedCode {
            code: _,
            language,
            path,
            start_line,
            end_line,
        } => {
            let start_line = start_line
                .map(|n| format!("<StartLine>{n}</StartLine>\n"))
                .unwrap_or_default();
            let end_line = end_line
                .map(|n| format!("<EndLine>{n}</EndLine>\n"))
                .unwrap_or_default();

            format!(
                "<QuotedCode>\n\
                <Code>[REDACTED]</Code>\n\
                <Language>{language}</Language>\n\
                <Path>{path}</Path>\n\
                {start_line}\
                {end_line}\
                </QuotedCode>"
            )
        }

        CodeChunk::GeneratedCode { code: _, language } => {
            format!(
                "<GeneratedCode>\n\
                <Code>[REDACTED]</Code>\n\
                <Language>{language}</Language>\n\
                </GeneratedCode>"
            )
        }
    })
}


pub fn encode_summarized(markdown: &str, conclusion: Option<&str>, model: &str) -> Result<String> {
    let article = xml_for_each(&encode(markdown, conclusion), |xml| {
        try_trim_code_xml(xml).ok()
    });
    let bpe = tiktoken_rs::get_bpe_from_model(model)?;
    Ok(limit_tokens(&article, bpe, 500).to_owned())
}


fn limit_tokens(text: &str, bpe: CoreBPE, max_tokens: usize) -> &str {
    let mut tokens = bpe.encode_ordinary(text);
    tokens.truncate(max_tokens);

    while !tokens.is_empty() {
        if let Ok(s) = bpe.decode(tokens.clone()) {
            return &text[..s.len()];
        }

        let _ = tokens.pop();
    }

    ""
}


/// generate such documents.
fn xml_for_each(article: &str, f: impl Fn(&str) -> Option<String>) -> String {
    let mut out = String::new();
    let mut rest = article;

    while let Some(captures) = regex!(r"\n\s*(<(\w+)>)").captures(rest) {
        let tag = captures.get(1).unwrap();
        let name = &rest[captures.get(2).unwrap().range()];

        out += &rest[..tag.start()];

        let xml = if let Some(m) = Regex::new(&format!(r"</{name}>")).unwrap().find(rest) {
            let xml = &rest[tag.start()..m.end()];
            rest = &rest[m.end()..];
            xml
        } else {
            let xml = &rest[tag.start()..];
            rest = "";
            xml
        };

        if let Some(update) = f(xml) {
            out += &update;
        } else {
            out += xml;
        }
    }

    out += rest;
    out
}

fn fixup_xml_code(xml: &str) -> Cow<str> {
    if !xml.trim().starts_with('<') {
        return Cow::Borrowed(xml);
    }

    if let Some(match_) = regex!("<(Generated|Quoted)Code>\\s*<Code>(.*)"sm)
        .captures(xml)
        .and_then(|cap| cap.get(2))
    {
        let mut buf = String::new();

        buf += &xml[..match_.start()];

        // First, we clean up incorrectly escaped symbols in the code block.
        {
            let s = &xml[match_.range()];

            let code_len = regex!("</Code>")
                .find(s)
                .map(|m| m.start())
                .unwrap_or(s.len());
            let (s, tail) = s.split_at(code_len);

            // The `regex` crate does not support negative lookahead, so we cannot write a regex
            // like `&(?!amp;)`. So, we just perform naive substitutions to first obtain an
            // unescaped copy of the string, and then re-escape it in order to fix up the result.
            //
            // This matters if the input string is something like `&amp;foo < &bar&lt;i32&gt;()`:
            //
            // - First, we convert that to `&foo < &bar<i32>()`
            // - Second, we convert it to `&amp;foo < &amp;bar&lt;i32&gt;`, our desired result.

            let s = regex!("&lt;"m).replace_all(s, "<");
            let s = regex!("&gt;"m).replace_all(&s, ">");
            let s = regex!("&amp;"m).replace_all(&s, "&");

            let s = regex!("&"m).replace_all(&s, "&amp;");
            let s = regex!("<"m).replace_all(&s, "&lt;");
            let s = regex!(">"m).replace_all(&s, "&gt;");

            buf += &s;
            buf += tail;
        }

        {
            // Next, we clean up the tags.
            //
            // Because the LLM is generating XML output token-by-token, we may end up in a
            // situation where closing tags are missing, or tags are half written. To fix this,
            // first we remove all half-complete opening or closing tags (e.g. `<foo` or `</`).
            // Then, we add missing closing tags, *in the order we expect them to appear in the
            // final XML output.* This is not perfect, but it should work well enough to allow us
            // to parse the XML.

            buf = regex!("<[^>]*$").replace_all(&buf, "").into_owned();

            for tag in [
                "Code",
                "Language",
                "Path",
                "StartLine",
                "EndLine",
                "QuotedCode",
                "GeneratedCode",
            ] {
                let opening_tag = format!("<{tag}>");
                let closing_tag = format!("</{tag}>");

                if buf.contains(&opening_tag) && !buf.contains(&closing_tag) {
                    buf += &closing_tag;
                }
            }
        }

        Cow::Owned(buf)
    } else {
        Cow::Borrowed(xml)
    }
}

pub fn encode(markdown: &str, conclusion: Option<&str>) -> String {
    let arena = comrak::Arena::new();
    let mut options = comrak::ComrakOptions::default();
    options.extension.footnotes = true;

    let root = comrak::parse_document(&arena, markdown, &options);

    for block in root.children() {
        offset_embedded_link_ranges(block, 1);

        let (info, literal) = match &mut block.data.borrow_mut().value {
            NodeValue::CodeBlock(block) => (block.info.clone(), block.literal.clone()),
            _ => continue,
        };

        let attributes = info
            .split(',')
            .filter_map(|param| {
                let mut iter = param.trim().split(':');

                let key = iter.next()?;
                let value = iter.next()?;

                Some((key.to_owned(), value.to_owned()))
            })
            .collect::<HashMap<String, String>>();

        let xml = attributes.get("type").and_then(|ty| match ty.as_str() {
            "Quoted" => {
                let path = attributes.get("path")?;
                let lang = attributes.get("lang")?;
                let mut lines = attributes.get("lines")?.split('-');

                let start_line = lines.next()?.parse::<usize>().ok()? + 1;
                let end_line = lines.next()?.parse::<usize>().ok()? + 1;

                Some(format!(
                    "<QuotedCode>\n\
                    <Code>\n\
                    {literal}\
                    </Code>\n\
                    <Language>{lang}</Language>\n\
                    <Path>{path}</Path>\n\
                    <StartLine>{start_line}</StartLine>\n\
                    <EndLine>{end_line}</EndLine>\n\
                    </QuotedCode>"
                ))
            }

            "Generated" => {
                let lang = attributes.get("lang")?;

                Some(format!(
                    "<GeneratedCode>\n\
                    <Code>\n\
                    {literal}\
                    </Code>\n\
                    <Language>{lang}</Language>\n\
                    </GeneratedCode>"
                ))
            }

            _ => None,
        });

        if let Some(xml) = xml {
            block.data.borrow_mut().value = NodeValue::HtmlBlock(NodeHtmlBlock {
                literal: xml,
                // The block type here is not used.
                block_type: 0,
            });
        }
    }

    let mut out = Vec::<u8>::new();
    comrak::format_commonmark(root, &options, &mut out).unwrap();
    let body = String::from_utf8_lossy(&out).trim().to_owned();

    if let Some(conclusion) = conclusion {
        body + "\n\n[^summary]: " + conclusion
    } else {
        body
    }
}




fn offset_embedded_link_ranges<'a>(element: &'a comrak::nodes::AstNode<'a>, offset: i32) -> bool {
    // We have to convert links to use 0-based indexes as the model works with 1-based indexes.
    //
    // TODO: We can update the model so that it works with 0-based indexes, and remove this
    // altogether.

    match &mut element.data.borrow_mut().value {
        NodeValue::Link(link) => {
            let url = mem::take(&mut link.url);
            link.url = url
                .split_once('#')
                .and_then(|(url, anchor)| {
                    if let Some((start, end)) = anchor.split_once('-') {
                        if !start.starts_with('L') || !end.starts_with('L') {
                            return None;
                        }

                        let start = start.get(1..)?.parse::<usize>().ok()?;
                        let end = end.get(1..)?.parse::<usize>().ok()?;

                        Some(format!(
                            "{url}#L{}-L{}",
                            start as i32 + offset,
                            end as i32 + offset,
                        ))
                    } else {
                        if !anchor.starts_with('L') {
                            return None;
                        }

                        let line = anchor.get(1..)?.parse::<usize>().ok()?;
                        Some(format!("{url}#L{}", line as i32 + offset))
                    }
                })
                .unwrap_or(url);

            true
        }

        // False positive lint, we want the side effects:
        // https://github.com/rust-lang/rust-clippy/issues/3351
        #[allow(clippy::unnecessary_fold)]
        _ => element
            .children()
            .map(|child| offset_embedded_link_ranges(child, offset))
            .fold(false, |a, e| a || e),
    }
}

fn sanitize(article: &str) -> String {
    let sanitized = xml_for_each(article, |code| Some(fixup_xml_code(code).into_owned()));
    regex!("<!--.*?-->")
        .replace_all(&sanitized, "")
        .replace("\n\n[^summary]:\n", "\n\n[^summary]: ")
}

fn xml_to_markdown(xml: &str) -> Result<String> {
    let code_chunk =
        de::from_str::<CodeChunk>(xml).context("failed to deserialize code chunk")?;

    Ok(code_chunk.to_markdown())
}

/// Decode an article.
///
/// If successful, this returns a tuple of `(body, conclusion)`.
pub fn decode(llm_message: &str) -> (String, Option<String>) {
    let sanitized = sanitize(llm_message);
    let markdown = xml_for_each(&sanitized, |code| xml_to_markdown(code).ok());

    // The `comrak` crate has a very unusual API which makes this logic difficult to follow. It
    // favours arena allocation instead of a tree-based AST, and requires `Write`rs to regenerate
    // markdown output.
    //
    // There are quirks to the parsing logic, comments have been added for clarity.

    let arena = comrak::Arena::new();
    let mut options = comrak::ComrakOptions::default();
    options.extension.footnotes = true;

    // We don't have an easy built-in way to generate a string with `comrak`, so we encapsulate
    // that logic here.
    let comrak_to_string = |node| {
        let mut out = Vec::<u8>::new();
        comrak::format_commonmark(node, &options, &mut out).unwrap();
        String::from_utf8_lossy(&out)
            .trim()
            .replace("\n\n<!-- end list -->", "")
    };

    // `comrak` will not recognize footnote definitions unless they have been referenced at least
    // once. To ensure our potential summary appears in the parse tree, we prepend the entire
    // response with a sentinel reference to the footnote. After parsing, we look for that
    // footnote and immediately remove (detach) it from the root node. This ensures that our
    // artifical reference does not appear in the output.

    let document = format!("[^summary]\n\n{markdown}");
    let root = comrak::parse_document(&arena, &document, &options);
    let mut children = root.children();
    // Detach the sentinel footnote reference.
    children.next().unwrap().detach();

    for block in children {
        offset_embedded_link_ranges(block, -1);

        match &block.data.borrow().value {
            NodeValue::Paragraph => {
                // Store our reconstructed markdown summary here, if it is found
                let mut buf: Option<String> = None;

                for child in block.children() {
                    // NB: We have to store this here due to more `comrak` quirks. Because `comrak`
                    // uses an arena-based API with `RefCell`s, we cannot both mutably borrow its
                    // inner data and also immutably generate a string from the outer container.
                    // So, we generate the string ahead of time in case we need it.
                    let child_text = comrak_to_string(child);

                    match &mut child.data.borrow_mut().value {
                        NodeValue::Text(s) if s.contains("[^summary]:") && buf.is_none() => {
                            let (l, r) = s.split_once("[^summary]:").unwrap();

                            buf = Some(r.trim_start().to_owned());
                            *s = l.trim_end().to_owned();
                        }

                        _ => {
                            if let Some(buf) = buf.as_mut() {
                                child.detach();
                                *buf += &child_text;
                                buf.push(' ');
                            }
                        }
                    }
                }

                if let Some(conclusion) = buf {
                    return (comrak_to_string(root), Some(conclusion.trim().to_owned()));
                }
            }

            NodeValue::FootnoteDefinition(def) if def.name == "summary" => (),
            _ => continue,
        };

        if let Some(first_child) = block.children().next() {
            if let NodeValue::Paragraph = &first_child.data.borrow().value {
                // We detach the summary from the main text, so that it does not end up in the final
                // article output.
                block.detach();
                return (comrak_to_string(root), Some(comrak_to_string(first_child)));
            }
        }
    }

    (comrak_to_string(root), None)
}