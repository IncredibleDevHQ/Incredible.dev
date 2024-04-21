use thiserror::Error;

#[derive(Debug, Error)]
pub enum AgentProcessingError {
    #[error("You're in LLM rate limit mode. Every codebase question is answered one at a time to save the rate limit. Continue the operation with returned task to continue the agent workflow.")]
    LLMRateLimitTriggered,
    #[error("Code Understanding API call failed: {0}")]
    CodeUnderStandingAgentCallFailed(String),
    #[error("Network error: {0}")]
    NetworkError(String),
}

impl From<anyhow::Error> for AgentProcessingError {
    fn from(err: anyhow::Error) -> Self {
        AgentProcessingError::NetworkError(err.to_string())
    }
}