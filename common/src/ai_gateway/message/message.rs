use anyhow::{Context, Result};
use std::fs::{File, OpenOptions};
use std::io::{stdout, Write};

use crate::ai_gateway::client::{ensure_model_capabilities, init_client, Message};
use crate::ai_gateway::config::AIGatewayConfig;
use crate::ai_gateway::config_files::ensure_parent_exists;
use crate::ai_gateway::function_calling::Function;
use crate::ai_gateway::input::Input;
use crate::ai_gateway::render::{render_stream, MarkdownRender};
use crate::ai_gateway::utils::{create_abort_signal, extract_block, now};

impl AIGatewayConfig {
    pub async fn use_llm(
        &mut self,
        text: &str,
        history: Option<Vec<Message>>,
        functions: Option<Vec<Function>>,
        include: Option<Vec<String>>,
        no_stream: bool,
        code_mode: bool,
    ) -> Result<String> {
        let input = Input::new(text, functions, history, include.unwrap_or_default())?;
        let mut client = init_client(self)?;
        ensure_model_capabilities(client.as_mut(), input.required_capabilities())?;

        let output = if no_stream {
            let output = client.send_message(input.clone()).await?;
            let output = if code_mode && output.trim_start().starts_with("```") {
                extract_block(&output)
            } else {
                output.clone()
            };
            if no_stream {
                let render_options = self.get_render_options()?;
                let mut markdown_render = MarkdownRender::init(render_options)?;
                println!("{}", markdown_render.render(&output).trim());
            } else {
                println!("{}", output);
            }
            output
        } else {
            let abort = create_abort_signal();
            render_stream(&input, client.as_ref(), self, abort)?
        };
        // Save the message/session
        self.save_message(input, &output)?;
        self.end_session()?;
        Ok(output)
    }

    fn open_message_file(&self) -> Result<File> {
        let path = Self::messages_file()?;
        ensure_parent_exists(&path)?;
        OpenOptions::new()
            .create(true)
            .append(true)
            .open(&path)
            .with_context(|| format!("Failed to create/append {}", path.display()))
    }

    pub fn save_message(&mut self, input: Input, output: &str) -> Result<()> {
        self.last_message = Some((input.clone(), output.to_string()));

        let mut file = self.open_message_file()?;
        if output.is_empty() {
            return Ok(());
        }
        let timestamp = now();
        let summary = input.summary();
        let input_markdown = input.render();
        let output = format!(
            "# CHAT: {summary} [{timestamp}]\n{input_markdown}\n--------\n{output}\n--------\n\n",
        );
        file.write_all(output.as_bytes())
            .with_context(|| "Failed to save message")
    }
}
