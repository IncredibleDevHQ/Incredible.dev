"""Slack presentation on the host: a Web API client, who a run answers, step phrases, live progress.

Everything here runs on the host with the bot token. The sandbox never sees the token, a Slack
URL or a Slack payload; the agent only sees files and messages the middleware writes.
"""

from design_agent.surfaces.slack.client import SlackClient, SlackError
from design_agent.surfaces.slack.target import (
    BoltSlackResolver,
    MdaSlackResolver,
    SlackBinding,
    SlackResolver,
    SlackSurface,
    SlackTarget,
)

__all__ = [
    "BoltSlackResolver",
    "MdaSlackResolver",
    "SlackBinding",
    "SlackClient",
    "SlackError",
    "SlackResolver",
    "SlackSurface",
    "SlackTarget",
]
