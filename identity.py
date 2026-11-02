"""MDA authentication for API clients and managed channels.

LangSmith API-key authentication: anyone with a workspace key can call the agent. For private
per-person conversations, configure MDA's Supabase identity (see OPERATIONS.md).
"""

from managed_deepagents import auth, define_identity

identity = define_identity(auth=auth.langsmith_api_key())
