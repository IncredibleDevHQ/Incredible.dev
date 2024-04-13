mod markdown;
mod stream;

pub use self::markdown::{MarkdownRender, RenderOptions};
use self::stream::{markdown_stream, raw_stream};

use crate::client::Client;
use crate::config::AIGatewayConfig;
use crate::input::Input;
use crate::utils::AbortSignal;
use log::debug;

use anyhow::{Context, Result};
use crossbeam::channel::{unbounded, Sender};
use crossbeam::sync::WaitGroup;
use is_terminal::IsTerminal;
use nu_ansi_term::{Color, Style};
use std::io::stdout;
use std::thread::spawn;

pub fn render_stream(
    input: &Input,
    client: &dyn Client,
    config: &AIGatewayConfig,
    abort: AbortSignal,
) -> Result<String> {
    let wg = WaitGroup::new();
    let wg_cloned = wg.clone();
    let mut stream_handler = {
        let (tx, rx) = unbounded();
        let abort_clone = abort.clone();
        spawn(move || {
            let run = move || {
                    raw_stream(&rx, &abort)
            };
            if let Err(err) = run() {
                render_error(err);
            }
            drop(wg_cloned);
        });
        ReplyHandler::new(tx, abort_clone)
    };
    let ret = client.send_message_streaming(input, &mut stream_handler);
    wg.wait();
    let output = stream_handler.get_buffer().to_string();
    match ret {
        Ok(_) => {
            println!();
            Ok(output)
        }
        Err(err) => {
            if !output.is_empty() {
                println!();
            }
            Err(err)
        }
    }
}

pub fn render_error(err: anyhow::Error ) {
    let err = format!("{err:?}");
        let style = Style::new().fg(Color::Red);
        eprintln!("{}", style.paint(err));
}

pub struct ReplyHandler {
    sender: Sender<ReplyEvent>,
    buffer: String,
    abort: AbortSignal,
}

impl ReplyHandler {
    pub fn new(sender: Sender<ReplyEvent>, abort: AbortSignal) -> Self {
        Self {
            sender,
            abort,
            buffer: String::new(),
        }
    }

    pub fn text(&mut self, text: &str) -> Result<()> {
        debug!("ReplyText: {}", text);
        if text.is_empty() {
            return Ok(());
        }
        self.buffer.push_str(text);
        let ret = self
            .sender
            .send(ReplyEvent::Text(text.to_string()))
            .with_context(|| "Failed to send ReplyEvent:Text");
        self.safe_ret(ret)?;
        Ok(())
    }

    pub fn done(&mut self) -> Result<()> {
        debug!("ReplyDone");
        let ret = self
            .sender
            .send(ReplyEvent::Done)
            .with_context(|| "Failed to send ReplyEvent::Done");
        self.safe_ret(ret)?;
        Ok(())
    }

    pub fn get_buffer(&self) -> &str {
        &self.buffer
    }

    pub fn get_abort(&self) -> AbortSignal {
        self.abort.clone()
    }

    fn safe_ret(&self, ret: Result<()>) -> Result<()> {
        if ret.is_err() && self.abort.aborted() {
            return Ok(());
        }
        ret
    }
}

pub enum ReplyEvent {
    Text(String),
    Done,
}
