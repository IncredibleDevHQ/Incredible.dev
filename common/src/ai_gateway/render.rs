use crate::ai_gateway::utils::AbortSignal;

use anyhow::{Context, Result};
use crossbeam::channel::Sender;
use log::debug;

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
